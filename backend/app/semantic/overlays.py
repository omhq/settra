import asyncio
import os
from typing import Any

import yaml

from app.auth import current_organization_id
from app.cube.client import CubeAPIError, load_cube_meta
from app.cube.model import list_semantic_overlay_files, read_semantic_overlay_file
from app.cube.projection import (
    OverlayListItemProjectionInput,
    OverlayListProjectionInput,
    OverlayProjectionInput,
    semantic_response_projector,
)

SEMANTIC_OVERLAY_COMPILE_ATTEMPTS = int(
    os.getenv("SEMANTIC_OVERLAY_COMPILE_ATTEMPTS", "10")
)
SEMANTIC_OVERLAY_COMPILE_SLEEP_SECONDS = float(
    os.getenv("SEMANTIC_OVERLAY_COMPILE_SLEEP_SECONDS", "0.5")
)
OVERLAY_MANIFEST_FIELDS = (
    "purpose",
    "requirement",
    "grain",
    "assumptions",
    "relationships",
    "metrics",
    "evidence",
    "validation",
    "approval",
)
REQUIRED_OVERLAY_MANIFEST_FIELDS = (
    "purpose",
    "requirement",
    "grain",
    "assumptions",
    "evidence",
)

semantic_overlay_write_lock = asyncio.Lock()


def overlay_path(path: str) -> str:
    normalized = os.path.normpath(path.strip().lstrip("/"))
    if normalized in {"", "."} or normalized.startswith("../"):
        raise ValueError("Invalid overlay path")
    if normalized.startswith("overlays/"):
        normalized = normalized.removeprefix("overlays/")
    if not normalized.endswith((".yaml", ".yml")):
        raise ValueError("Overlay path must end in .yaml or .yml")
    return f"overlays/{normalized}"


def generated_overlay_path(path: str) -> str:
    normalized = os.path.normpath(path.strip().lstrip("/"))
    if normalized.startswith("overlays/"):
        normalized = normalized.removeprefix("overlays/")

    tenant_prefix = f"generated/organizations/{current_organization_id()}/"
    if normalized.startswith("generated/organizations/"):
        if not normalized.startswith(tenant_prefix):
            raise ValueError("Semantic overlay is outside the active organization")
    else:
        normalized = normalized.removeprefix("generated/")
        normalized = f"{tenant_prefix}{normalized}"

    normalized_path = overlay_path(normalized)
    if not normalized_path.startswith("overlays/generated/"):
        raise ValueError("Only generated semantic overlays can be modified")
    return normalized_path


def parse_overlay_yaml(content: str) -> dict[str, Any]:
    try:
        parsed = yaml.safe_load(content) if content.strip() else {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid overlay YAML: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Overlay YAML must contain a mapping")
    return parsed


def declared_model_names(parsed: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for key in ("cubes", "views"):
        items = parsed.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict) and isinstance(item.get("name"), str):
                names.append(item["name"])
    return names


def compiled_cube_names(meta: dict[str, Any]) -> set[str]:
    cubes = meta.get("cubes") if isinstance(meta, dict) else []
    return {
        cube["name"]
        for cube in cubes
        if isinstance(cube, dict) and isinstance(cube.get("name"), str)
    }


def semantic_overlay_manifest(parsed: dict[str, Any]) -> dict[str, Any]:
    models: list[dict[str, Any]] = []

    for model_type in ("cubes", "views"):
        items = parsed.get(model_type)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                continue
            settra_meta = _settra_meta(item)
            manifest = {
                field: settra_meta[field]
                for field in OVERLAY_MANIFEST_FIELDS
                if field in settra_meta
            }
            missing_fields = [
                field
                for field in REQUIRED_OVERLAY_MANIFEST_FIELDS
                if field not in manifest
            ]
            models.append(
                {
                    "name": item["name"],
                    "type": model_type.removesuffix("s"),
                    "title": item.get("title"),
                    "description": item.get("description"),
                    "manifest": manifest or None,
                    "manifest_complete": not missing_fields,
                    "missing_manifest_fields": missing_fields,
                }
            )

    model_manifests = [model for model in models if model["manifest"]]
    if models and all(model["manifest_complete"] for model in models):
        status = "complete"
    elif model_manifests:
        status = "partial"
    else:
        status = "missing"

    first_manifest = model_manifests[0]["manifest"] if model_manifests else {}
    first_model = models[0] if models else {}
    return {
        "status": status,
        "purpose": first_manifest.get("purpose") or first_model.get("description"),
        "requirement": first_manifest.get("requirement"),
        "evidence": first_manifest.get("evidence"),
        "models": models,
    }


def require_complete_overlay_manifest(content: str) -> dict[str, Any]:
    manifest = semantic_overlay_manifest(parse_overlay_yaml(content))
    if manifest.get("status") != "complete":
        missing = sorted(
            {
                field
                for model in manifest.get("models", [])
                for field in model.get("missing_manifest_fields", [])
            }
        )
        detail = f" Missing fields: {', '.join(missing)}." if missing else ""
        raise ValueError(
            "Generated overlays require a complete meta.settra provenance manifest."
            f"{detail}"
        )
    return manifest


async def list_overlay_details(
    scope: str = "all",
    *,
    allowed_names: set[str] | None = None,
) -> dict[str, Any]:
    normalized_scope = scope.strip().lower().replace("-", "_")
    allowed_scopes = {"all", "generated", "hand_authored"}
    if normalized_scope not in allowed_scopes:
        raise ValueError("scope must be all, generated, or hand_authored")

    files = list_semantic_overlay_files(allowed_names=allowed_names)
    if normalized_scope == "generated":
        files = [
            file for file in files if file.get("source_type") == "generated_overlay"
        ]
    elif normalized_scope == "hand_authored":
        files = [file for file in files if file.get("source_type") == "overlay"]

    meta, metadata_error = await _load_optional_cube_meta()
    compiled_names = compiled_cube_names(meta)
    overlays: list[OverlayListItemProjectionInput] = []

    for file in files:
        detail = read_semantic_overlay_file(str(file["path"]))
        parsed, parse_error = _parse_overlay_for_discovery(str(detail["content"]))
        names = [*file.get("cube_names", []), *file.get("view_names", [])]
        if allowed_names is not None and (
            not names or not set(names).issubset(allowed_names)
        ):
            continue
        overlays.append(
            OverlayListItemProjectionInput(
                path=str(file["path"]),
                model_names=names,
                manifest=semantic_overlay_manifest(parsed),
                compile_status=_overlay_compile_status(
                    file,
                    compiled_names,
                    metadata_error,
                ),
                parse_error=parse_error,
            )
        )

    return semantic_response_projector.overlay_list(
        OverlayListProjectionInput(overlays=overlays, error=metadata_error)
    )


async def get_overlay_detail(
    path: str,
    *,
    allowed_names: set[str] | None = None,
) -> dict[str, Any]:
    normalized = overlay_path(path)
    file = read_semantic_overlay_file(normalized)
    parsed, parse_error = _parse_overlay_for_discovery(str(file["content"]))
    meta, metadata_error = await _load_optional_cube_meta()
    names = [*file.get("cube_names", []), *file.get("view_names", [])]
    if allowed_names is not None and (
        not names or not set(names).issubset(allowed_names)
    ):
        raise ValueError("Semantic overlay is outside the selected collection")
    return semantic_response_projector.overlay(
        OverlayProjectionInput(
            path=str(file["path"]),
            content=str(file["content"]),
            model_names=names,
            manifest=semantic_overlay_manifest(parsed),
            compile_status=_overlay_compile_status(
                file,
                compiled_cube_names(meta),
                metadata_error,
            ),
            parse_error=parse_error,
        )
    )


async def wait_for_compiled_model_names(
    expected_names: list[str],
    *,
    after_compiler_id: str | None = None,
    validation_token: str | None = None,
) -> dict[str, Any]:
    expected = {name for name in expected_names if isinstance(name, str)}
    status: dict[str, Any] = {
        "connected": False,
        "compiled": False,
        "cube_count": 0,
        "missing_names": sorted(expected),
        "compiler_id": None,
        "validation_token_seen": False,
        "error": None,
    }

    for attempt in range(SEMANTIC_OVERLAY_COMPILE_ATTEMPTS):
        try:
            meta = await load_cube_meta()
            cubes = meta.get("cubes") if isinstance(meta, dict) else []
            names = {
                cube.get("name")
                for cube in cubes
                if isinstance(cube, dict) and isinstance(cube.get("name"), str)
            }
            missing = sorted(expected - names)
            token_names = {
                cube.get("name")
                for cube in cubes
                if isinstance(cube, dict)
                and isinstance(cube.get("name"), str)
                and _cube_validation_token(cube) == validation_token
            }
            token_missing = sorted(expected - token_names) if validation_token else []
            compiler_id = meta.get("compilerId") if isinstance(meta, dict) else None
            compiler_reloaded = (
                after_compiler_id is None or compiler_id != after_compiler_id
            )
            validation_seen = not validation_token or not token_missing
            status = {
                "connected": True,
                "compiled": (
                    bool(expected)
                    and not missing
                    and compiler_reloaded
                    and validation_seen
                ),
                "cube_count": len(cubes) if isinstance(cubes, list) else 0,
                "missing_names": missing,
                "compiler_id": compiler_id,
                "validation_token_seen": bool(validation_token) and not token_missing,
                "error": None,
            }
            if not missing and compiler_reloaded and validation_seen:
                return status
        except CubeAPIError as exc:
            status = {
                "connected": False,
                "compiled": False,
                "cube_count": 0,
                "missing_names": sorted(expected),
                "compiler_id": None,
                "validation_token_seen": False,
                "error": exc.message,
            }

        if attempt < SEMANTIC_OVERLAY_COMPILE_ATTEMPTS - 1:
            await asyncio.sleep(SEMANTIC_OVERLAY_COMPILE_SLEEP_SECONDS)

    return status


async def wait_for_removed_model_names(
    removed_names: list[str],
) -> dict[str, Any]:
    removed = {name for name in removed_names if isinstance(name, str)}
    status: dict[str, Any] = {
        "connected": False,
        "removed": False,
        "cube_count": 0,
        "remaining_names": sorted(removed),
        "error": None,
    }

    for attempt in range(SEMANTIC_OVERLAY_COMPILE_ATTEMPTS):
        try:
            meta = await load_cube_meta()
            cubes = meta.get("cubes") if isinstance(meta, dict) else []
            names = {
                cube.get("name")
                for cube in cubes
                if isinstance(cube, dict) and isinstance(cube.get("name"), str)
            }
            remaining = sorted(removed & names)
            status = {
                "connected": True,
                "removed": not remaining,
                "cube_count": len(cubes) if isinstance(cubes, list) else 0,
                "remaining_names": remaining,
                "error": None,
            }
            if not remaining:
                return status
        except CubeAPIError as exc:
            status = {
                "connected": False,
                "removed": False,
                "cube_count": 0,
                "remaining_names": sorted(removed),
                "error": exc.message,
            }

        if attempt < SEMANTIC_OVERLAY_COMPILE_ATTEMPTS - 1:
            await asyncio.sleep(SEMANTIC_OVERLAY_COMPILE_SLEEP_SECONDS)

    return status


def _settra_meta(item: dict[str, Any]) -> dict[str, Any]:
    meta = item.get("meta")
    if not isinstance(meta, dict):
        return {}
    settra = meta.get("settra")
    if not isinstance(settra, dict):
        return {}
    nested = settra.get("overlay")
    return nested if isinstance(nested, dict) else settra


def _parse_overlay_for_discovery(
    content: str,
) -> tuple[dict[str, Any], str | None]:
    try:
        return parse_overlay_yaml(content), None
    except ValueError as exc:
        return {}, str(exc)


async def _load_optional_cube_meta() -> tuple[dict[str, Any], str | None]:
    try:
        return await load_cube_meta(), None
    except CubeAPIError as exc:
        return {}, exc.message


def _overlay_compile_status(
    file: dict[str, Any],
    compiled_names: set[str],
    metadata_error: str | None,
) -> dict[str, Any]:
    names = [*file.get("cube_names", []), *file.get("view_names", [])]
    missing_names = sorted(set(names) - compiled_names)
    compiled_models = sorted(set(names) & compiled_names)
    if metadata_error:
        status = "unknown"
    elif not names:
        status = "empty"
    elif not missing_names:
        status = "compiled"
    elif compiled_models:
        status = "partial"
    else:
        status = "not_compiled"
    return {
        "connected": metadata_error is None,
        "status": status,
        "compiled": status == "compiled",
        "compiled_names": compiled_models,
        "missing_names": missing_names,
        "error": metadata_error,
    }


def _cube_validation_token(cube: dict[str, Any]) -> str | None:
    meta = cube.get("meta")
    if not isinstance(meta, dict):
        return None
    settra = meta.get("settra")
    if not isinstance(settra, dict):
        return None
    token = settra.get("validation_token")
    return token if isinstance(token, str) else None
