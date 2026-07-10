import re
import uuid
import copy

from typing import Annotated, Any, NotRequired, TypedDict

import yaml

from fastapi import HTTPException
from mcp.types import ToolAnnotations
from pydantic import Field

from app.cube.client import CubeAPIError, load_cube_meta
from app.cube.model import (
    delete_generated_model_file,
    read_semantic_overlay_file,
    save_model_file,
    source_definition_index,
)
from app.cube.projection import (
    OverlayValidationProjectionInput,
    semantic_response_projector,
)
from app.cube.query import execute_cube_query_payload

from .common import (
    compiled_cube_names,
    declared_model_names,
    generated_overlay_path,
    mcp_server,
    overlay_path,
    run_mcp_action,
    semantic_overlay_write_lock,
    semantic_overlay_manifest,
    wait_for_compiled_model_names,
    wait_for_removed_model_names,
)


class ValidationIssue(TypedDict):
    code: str
    message: str
    detail: NotRequired[str]
    cube: NotRequired[str]
    source_path: NotRequired[str]
    missing_names: NotRequired[list[str]]
    description: NotRequired[str]
    error: NotRequired[str]


class ValidationCubeStatus(TypedDict):
    connected: bool
    compiled: bool
    cube_count: int
    missing_names: list[str]
    compiler_id: NotRequired[str | None]
    validation_token_seen: NotRequired[bool]
    error: str | None


class ValidationCleanup(TypedDict):
    attempted: bool
    removed: bool
    error: str | None
    path: NotRequired[str]
    restored: NotRequired[bool]
    cube: NotRequired[dict[str, Any]]


class ValidationEvidence(TypedDict):
    declared_cube_count: int
    referenced_cube_count: int
    referenced_physical_tables: list[str]
    current_compiled_cube_count: int
    test_query_count: int
    successful_test_query_count: int


class ValidationTestQueryResult(TypedDict):
    description: str
    success: bool
    row_count: int
    error: str | None


class SemanticOverlayValidationResult(TypedDict):
    valid: bool
    ready_to_save: bool
    compiles: bool
    proposed_path: str | None
    declared_cubes: list[str]
    referenced_cubes: list[str]
    queried_cubes: list[str]
    grain: str | None
    manifest: dict[str, Any]
    warnings: list[ValidationIssue]
    errors: list[ValidationIssue]
    evidence: ValidationEvidence
    cube: ValidationCubeStatus
    cleanup: ValidationCleanup
    test_queries: list[ValidationTestQueryResult]


@mcp_server.tool(
    name="validate_semantic_overlay",
    title="Validate Semantic Overlay",
    description=(
        "Validate proposed Cube YAML without leaving it persisted. Use this after "
        "inspect/profile/draft and before asking the user to approve creation or "
        "an update. For replacements, set path to the existing generated overlay "
        "path so the validator can distinguish an update from a duplicate model. "
        "The validator checks declared models, references, and the structured "
        "meta.settra manifest for purpose, requirement, grain, approved "
        "assumptions, relationships, metrics, and evidence. It performs an "
        "ephemeral Cube compile, runs optional Cube REST test_queries, and removes "
        "the validation file. valid reports technical success; ready_to_save also "
        "requires a complete provenance manifest. Successful validation is compact; "
        "compiler and cleanup diagnostics are included when validation fails."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    structured_output=True,
)
async def validate_semantic_overlay(
    content: Annotated[
        str,
        Field(description="Complete Cube YAML overlay content to validate."),
    ],
    path: Annotated[
        str,
        Field(
            description=(
                "Proposed generated overlay path. For updates, pass the existing "
                "generated overlay path exactly; using a temporary path for a "
                "replacement will correctly fail with DUPLICATE_MODEL_NAME."
            )
        ),
    ] = "generated/validation.yaml",
    test_queries: Annotated[
        list[dict[str, Any]] | None,
        Field(description="Optional Cube REST query objects to run after compile."),
    ] = None,
) -> dict[str, Any]:
    """Dry-run validate a proposed semantic overlay without persisting it."""

    async with semantic_overlay_write_lock:
        result = await run_mcp_action(
            _validate_semantic_overlay(
                content=content,
                path=path,
                test_queries=test_queries or [],
            )
        )

        return semantic_response_projector.overlay_validation(
            OverlayValidationProjectionInput(result=result)
        )


async def _validate_semantic_overlay(
    *,
    content: str,
    path: str,
    test_queries: list[dict[str, Any]],
) -> SemanticOverlayValidationResult:
    warnings: list[ValidationIssue] = []
    errors: list[ValidationIssue] = []
    cleanup: dict[str, Any] = {
        "attempted": False,
        "removed": False,
        "error": None,
    }
    compile_status: dict[str, Any] = {
        "connected": False,
        "compiled": False,
        "cube_count": 0,
        "missing_names": [],
        "error": None,
    }
    test_results: list[ValidationTestQueryResult] = []
    proposed_path: str | None = None

    try:
        proposed_path = overlay_path(path)
    except ValueError as exc:
        errors.append(_validation_issue("INVALID_PATH", str(exc)))

    parsed = _parse_overlay_yaml(content, errors)

    if parsed is None:
        return _validation_result(
            proposed_path=proposed_path,
            parsed=None,
            warnings=warnings,
            errors=errors,
            compile_status=compile_status,
            cleanup=cleanup,
            test_results=test_results,
        )

    declared_names = declared_model_names(parsed)

    if not declared_names:
        errors.append(
            _validation_issue(
                "NO_CUBES_OR_VIEWS",
                "Overlay YAML must declare at least one cube or view.",
            )
        )

    current_names: set[str] = set()
    source_definitions: dict[str, Any] = {}
    current_compiler_id: str | None = None

    try:
        meta = await load_cube_meta()
        current_names = compiled_cube_names(meta)
        current_compiler_id = meta.get("compilerId")
        source_definitions = source_definition_index()
    except CubeAPIError as exc:
        warnings.append(
            _validation_issue(
                "CURRENT_METADATA_UNAVAILABLE",
                "Could not fetch current Cube metadata before validation.",
                detail=exc.message,
            )
        )
    except Exception as exc:
        warnings.append(
            _validation_issue(
                "CURRENT_SOURCE_INDEX_UNAVAILABLE",
                "Could not inspect all current Cube source files before validation.",
                detail=f"{exc.__class__.__name__}: {exc}",
            )
        )

    _add_documentation_warnings(parsed, warnings)

    references = _overlay_references(parsed, test_queries)
    all_cube_references = references["cube_references"] | references["test_query_cubes"]
    unresolved_references = sorted(
        all_cube_references - set(declared_names) - current_names
    )
    duplicate_names = sorted(set(declared_names) & current_names)

    for name in unresolved_references:
        warnings.append(
            _validation_issue(
                "UNRESOLVED_CUBE_REFERENCE",
                f"Referenced cube '{name}' is not declared in the overlay or compiled metadata.",
                cube=name,
            )
        )

    for name in duplicate_names:
        source_path = (
            source_definitions.get(name, {}).get("path")
            if isinstance(source_definitions.get(name), dict)
            else None
        )

        if proposed_path and source_path == proposed_path:
            continue

        message = (
            f"Overlay declares '{name}', which already exists in compiled metadata."
        )

        if isinstance(source_path, str) and source_path.startswith(
            "overlays/generated/"
        ):
            message += (
                " If this is an update, call validate_semantic_overlay with "
                f"path='{source_path}' so the existing model is replaced during "
                "validation instead of treated as a duplicate."
            )

        errors.append(
            _validation_issue(
                "DUPLICATE_MODEL_NAME",
                message,
                cube=name,
                source_path=source_path,
            )
        )

    if errors:
        return _validation_result(
            proposed_path=proposed_path,
            parsed=parsed,
            warnings=warnings,
            errors=errors,
            compile_status=compile_status,
            cleanup=cleanup,
            test_results=test_results,
            current_names=current_names,
            references=references,
        )

    validation_path = generated_overlay_path(f"_validation/{uuid.uuid4().hex}.yaml")
    validation_token = uuid.uuid4().hex
    existing_file: dict[str, Any] | None = None

    if proposed_path and proposed_path.startswith("overlays/generated/"):
        try:
            existing_file = read_semantic_overlay_file(proposed_path)
            validation_path = proposed_path
        except HTTPException as exc:
            if exc.status_code != 404:
                errors.append(_validation_issue("OVERLAY_READ_FAILED", str(exc.detail)))

    if errors:
        return _validation_result(
            proposed_path=proposed_path,
            parsed=parsed,
            warnings=warnings,
            errors=errors,
            compile_status=compile_status,
            cleanup=cleanup,
            test_results=test_results,
            current_names=current_names,
            references=references,
        )

    try:
        saved = save_model_file(
            validation_path,
            _validation_content(parsed, validation_token),
        )
        file = saved.get("file") if isinstance(saved.get("file"), dict) else {}
        expected_names = [*file.get("cube_names", []), *file.get("view_names", [])]
        compile_status = await wait_for_compiled_model_names(
            expected_names,
            after_compiler_id=current_compiler_id if existing_file else None,
            validation_token=validation_token,
        )

        if not compile_status.get("compiled"):
            errors.append(
                _validation_issue(
                    "COMPILE_FAILED",
                    "Cube did not compile all declared overlay names.",
                    detail=compile_status.get("error"),
                    missing_names=compile_status.get("missing_names", []),
                )
            )
        else:
            test_results = await _run_overlay_test_queries(test_queries)

            for result in test_results:
                if not result.get("success"):
                    errors.append(
                        _validation_issue(
                            "TEST_QUERY_FAILED",
                            "A validation test query failed.",
                            description=result.get("description"),
                            error=result.get("error"),
                        )
                    )
    except HTTPException as exc:
        errors.append(_validation_issue("INVALID_OVERLAY", str(exc.detail)))
    except Exception as exc:
        errors.append(
            _validation_issue(
                "VALIDATION_ERROR",
                f"{exc.__class__.__name__}: {exc}",
            )
        )
    finally:
        if existing_file:
            cleanup = await _restore_validation_overlay(
                validation_path,
                str(existing_file["content"]),
                [
                    *existing_file.get("cube_names", []),
                    *existing_file.get("view_names", []),
                ],
                compile_status.get("compiler_id"),
            )
        else:
            cleanup = await _cleanup_validation_overlay(validation_path, declared_names)

    return _validation_result(
        proposed_path=proposed_path,
        parsed=parsed,
        warnings=warnings,
        errors=errors,
        compile_status=compile_status,
        cleanup=cleanup,
        test_results=test_results,
        current_names=current_names,
        references=references,
    )


def _validation_content(parsed: dict[str, Any], token: str) -> str:
    validation_model = copy.deepcopy(parsed)

    for key in ("cubes", "views"):
        items = validation_model.get(key)

        if not isinstance(items, list):
            continue

        for item in items:
            if not isinstance(item, dict):
                continue

            meta = item.get("meta")

            if not isinstance(meta, dict):
                meta = {}

            settra = meta.get("settra")

            if not isinstance(settra, dict):
                settra = {}

            settra["validation_token"] = token
            meta["settra"] = settra
            item["meta"] = meta

    return yaml.safe_dump(validation_model, sort_keys=False, allow_unicode=False)


def _parse_overlay_yaml(
    content: str,
    errors: list[ValidationIssue],
) -> dict[str, Any] | None:
    if not content.strip():
        errors.append(_validation_issue("EMPTY_OVERLAY", "Overlay content is empty."))
        return None

    try:
        parsed = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        errors.append(_validation_issue("INVALID_YAML", f"Invalid YAML: {exc}"))
        return None

    if not isinstance(parsed, dict):
        errors.append(
            _validation_issue(
                "INVALID_YAML_SHAPE",
                "Overlay YAML must contain a mapping.",
            )
        )
        return None

    return parsed


def _add_documentation_warnings(
    parsed: dict[str, Any],
    warnings: list[ValidationIssue],
) -> None:
    text = _model_text(parsed)
    measures = _model_measures(parsed)
    physical_tables = _physical_table_references(parsed)
    cube_references = _overlay_references(parsed, [])["cube_references"]
    manifest = semantic_overlay_manifest(parsed)
    manifest_models = manifest.get("models", [])

    if manifest.get("status") != "complete":
        missing = sorted(
            {
                field
                for model in manifest_models
                for field in model.get("missing_manifest_fields", [])
            }
        )
        warnings.append(
            _validation_issue(
                "INCOMPLETE_PROVENANCE_MANIFEST",
                "Each declared model should preserve structured provenance under meta.settra.",
                detail=f"Missing fields: {', '.join(missing)}" if missing else None,
            )
        )

    if not _manifest_field(manifest_models, "purpose") and not _has_any(
        text, ["purpose", "use this cube", "use this view"]
    ):
        warnings.append(
            _validation_issue(
                "MISSING_PURPOSE",
                "Document the overlay's business purpose in meta.settra.purpose.",
            )
        )

    if not _extract_grain(parsed):
        warnings.append(
            _validation_issue(
                "MISSING_GRAIN",
                "Document the overlay grain, for example 'one row per successful charge'.",
            )
        )

    if not _manifest_field(manifest_models, "assumptions") and not _has_any(
        text, ["assumption", "assumptions", "caveat", "caveats"]
    ):
        warnings.append(
            _validation_issue(
                "MISSING_ASSUMPTIONS",
                "Document approved assumptions or caveats in meta.settra.assumptions.",
            )
        )

    if measures and any(
        not isinstance(measure.get("description"), str)
        or not measure["description"].strip()
        for measure in measures
    ):
        warnings.append(
            _validation_issue(
                "MISSING_METRIC_DEFINITIONS",
                "One or more measures lack descriptions explaining the metric definition.",
            )
        )

    if (
        (len(physical_tables) > 1 or cube_references)
        and not _manifest_field(manifest_models, "relationships")
        and not _has_any(text, ["relationship", "join", "match", "cardinality"])
    ):
        warnings.append(
            _validation_issue(
                "MISSING_RELATIONSHIP_RULES",
                "Document relationship rules, match keys, and join cardinality.",
            )
        )

    if _has_any(text, ["revenue", "amount", "currency", "refund"]) and not _has_any(
        text, ["currency", "/ 100", "minor currency", "major currency"]
    ):
        warnings.append(
            _validation_issue(
                "CURRENCY_HANDLING_NOT_DOCUMENTED",
                "Financial overlays should document currency and minor/major-unit handling.",
            )
        )

    if not _manifest_field(manifest_models, "evidence") and not _has_any(
        text, ["evidence", "validated", "validation", "coverage"]
    ):
        warnings.append(
            _validation_issue(
                "MISSING_EVIDENCE",
                "Preserve supporting evidence or validation results in meta.settra.evidence.",
            )
        )


def _manifest_field(models: Any, field: str) -> bool:
    if not isinstance(models, list):
        return False

    return any(
        isinstance(model, dict)
        and isinstance(model.get("manifest"), dict)
        and field in model["manifest"]
        for model in models
    )


def _model_text(value: Any) -> str:
    parts: list[str] = []

    def visit(item: Any) -> None:
        if isinstance(item, str):
            parts.append(item.lower())
        elif isinstance(item, dict):
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return " ".join(parts)


def _model_measures(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    measures: list[dict[str, Any]] = []

    for key in ("cubes", "views"):
        items = parsed.get(key)

        if not isinstance(items, list):
            continue

        for item in items:
            if not isinstance(item, dict):
                continue

            item_measures = item.get("measures")

            if isinstance(item_measures, list):
                measures.extend(
                    measure for measure in item_measures if isinstance(measure, dict)
                )

    return measures


def _extract_grain(parsed: dict[str, Any]) -> str | None:
    manifest = semantic_overlay_manifest(parsed)

    for model in manifest.get("models", []):
        model_manifest = model.get("manifest")

        if isinstance(model_manifest, dict) and isinstance(
            model_manifest.get("grain"), str
        ):
            return model_manifest["grain"]

    text = _model_text(parsed)
    grain_match = re.search(
        r"(?:grain|one row per)[^.\n]{0,120}",
        text,
        flags=re.IGNORECASE,
    )

    if grain_match:
        return grain_match.group(0).strip()

    for key in ("cubes", "views"):
        items = parsed.get(key)

        if not isinstance(items, list):
            continue

        for item in items:
            if not isinstance(item, dict):
                continue

            dimensions = item.get("dimensions")

            if not isinstance(dimensions, list):
                continue

            for dimension in dimensions:
                if (
                    isinstance(dimension, dict)
                    and dimension.get("primary_key")
                    and isinstance(dimension.get("name"), str)
                ):
                    return f"primary key: {item.get('name')}.{dimension['name']}"

    return None


def _overlay_references(
    parsed: dict[str, Any],
    test_queries: list[dict[str, Any]],
) -> dict[str, Any]:
    cube_references: set[str] = set()

    for key in ("cubes", "views"):
        items = parsed.get(key)

        if not isinstance(items, list):
            continue

        for item in items:
            if not isinstance(item, dict):
                continue

            joins = item.get("joins")

            if isinstance(joins, list):
                for join in joins:
                    if isinstance(join, dict) and isinstance(join.get("name"), str):
                        cube_references.add(join["name"])

    for text in _string_values(parsed):
        cube_references.update(_cube_references_from_text(text))

    return {
        "cube_references": cube_references,
        "test_query_cubes": _cube_references_from_test_queries(test_queries),
        "physical_tables": _physical_table_references(parsed),
    }


def _string_values(value: Any) -> list[str]:
    values: list[str] = []

    def visit(item: Any) -> None:
        if isinstance(item, str):
            values.append(item)
        elif isinstance(item, dict):
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return values


def _cube_references_from_text(text: str) -> set[str]:
    references: set[str] = set()

    for match in re.finditer(r"\{([A-Za-z][A-Za-z0-9_]*)(?:\.[A-Za-z0-9_]+)?\}", text):
        name = match.group(1)
        if name != "CUBE":
            references.add(name)

    return references


def _cube_references_from_test_queries(
    test_queries: list[dict[str, Any]],
) -> set[str]:
    references: set[str] = set()

    for item in test_queries:
        query = item.get("query") if isinstance(item.get("query"), dict) else item

        if not isinstance(query, dict):
            continue

        for key in ("measures", "dimensions", "segments"):
            members = query.get(key)

            if not isinstance(members, list):
                continue

            for member in members:
                if isinstance(member, str) and "." in member:
                    references.add(member.split(".", 1)[0])

    return references


def _physical_table_references(parsed: dict[str, Any]) -> list[str]:
    tables: set[str] = set()

    for text in _string_values(parsed):
        for match in re.finditer(r'"([^"]+)"\."([^"]+)"', text):
            tables.add(f"{match.group(1)}.{match.group(2)}")

    return sorted(tables)


async def _run_overlay_test_queries(
    test_queries: list[dict[str, Any]],
) -> list[ValidationTestQueryResult]:
    results: list[ValidationTestQueryResult] = []

    for index, item in enumerate(test_queries, start=1):
        description = (
            item.get("description")
            if isinstance(item.get("description"), str)
            else f"Test query {index}"
        )
        query = item.get("query") if isinstance(item.get("query"), dict) else item
        result: ValidationTestQueryResult = {
            "description": description,
            "success": False,
            "row_count": 0,
            "error": None,
        }

        if not isinstance(query, dict):
            result["error"] = "Test query must be a Cube query object."

            results.append(result)
            continue

        try:
            response = await execute_cube_query_payload({"query": query})
            data = response.get("data")

            result.update(
                {
                    "success": True,
                    "row_count": len(data) if isinstance(data, list) else 0,
                }
            )
        except HTTPException as exc:
            result["error"] = str(exc.detail)
        except Exception as exc:
            result["error"] = f"{exc.__class__.__name__}: {exc}"

        results.append(result)

    return results


async def _cleanup_validation_overlay(
    temp_path: str,
    declared_names: list[str],
) -> dict[str, Any]:
    cleanup: dict[str, Any] = {
        "attempted": True,
        "removed": False,
        "path": temp_path,
        "error": None,
    }

    try:
        delete_generated_model_file(temp_path)

        cleanup["cube"] = await wait_for_removed_model_names(declared_names)
        cleanup["removed"] = True
    except HTTPException as exc:
        if exc.status_code == 404:
            cleanup["removed"] = True
        else:
            cleanup["error"] = str(exc.detail)
    except Exception as exc:
        cleanup["error"] = f"{exc.__class__.__name__}: {exc}"

    return cleanup


async def _restore_validation_overlay(
    path: str,
    original_content: str,
    original_names: list[str],
    after_compiler_id: str | None,
) -> dict[str, Any]:
    cleanup: dict[str, Any] = {
        "attempted": True,
        "removed": True,
        "restored": False,
        "path": path,
        "error": None,
    }

    try:
        save_model_file(path, original_content)

        cleanup["cube"] = await wait_for_compiled_model_names(
            original_names,
            after_compiler_id=after_compiler_id,
        )
        cleanup["restored"] = True
    except HTTPException as exc:
        cleanup["error"] = str(exc.detail)
    except Exception as exc:
        cleanup["error"] = f"{exc.__class__.__name__}: {exc}"

    return cleanup


def _validation_result(
    *,
    proposed_path: str | None,
    parsed: dict[str, Any] | None,
    warnings: list[ValidationIssue],
    errors: list[ValidationIssue],
    compile_status: dict[str, Any],
    cleanup: dict[str, Any],
    test_results: list[ValidationTestQueryResult],
    current_names: set[str] | None = None,
    references: dict[str, Any] | None = None,
) -> SemanticOverlayValidationResult:
    parsed = parsed or {}
    declared_names = declared_model_names(parsed)
    references = references or {
        "cube_references": set(),
        "test_query_cubes": set(),
        "physical_tables": [],
    }
    declared_name_set = set(declared_names)
    source_references = references["cube_references"] - declared_name_set
    failed_tests = [result for result in test_results if not result.get("success")]
    compiles = bool(compile_status.get("compiled"))
    manifest = semantic_overlay_manifest(parsed)
    technically_valid = not errors and compiles and not failed_tests

    return {
        "valid": technically_valid,
        "ready_to_save": technically_valid and manifest.get("status") == "complete",
        "compiles": compiles,
        "proposed_path": proposed_path,
        "declared_cubes": declared_names,
        "referenced_cubes": sorted(source_references),
        "queried_cubes": sorted(references["test_query_cubes"]),
        "grain": _extract_grain(parsed),
        "manifest": manifest,
        "warnings": warnings,
        "errors": errors,
        "evidence": {
            "declared_cube_count": len(declared_names),
            "referenced_cube_count": len(source_references),
            "referenced_physical_tables": references["physical_tables"],
            "current_compiled_cube_count": len(current_names or set()),
            "test_query_count": len(test_results),
            "successful_test_query_count": len(test_results) - len(failed_tests),
        },
        "cube": compile_status,
        "cleanup": cleanup,
        "test_queries": test_results,
    }


def _validation_issue(
    code: str,
    message: str,
    **extra: Any,
) -> ValidationIssue:
    return {
        "code": code,
        "message": message,
        **{key: value for key, value in extra.items() if value is not None},
    }


def _has_any(text: str, needles: list[str]) -> bool:
    return any(needle in text for needle in needles)
