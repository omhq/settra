import unittest

from unittest.mock import AsyncMock, patch

from app.cube.projection import (
    OverlayCreateProjectionInput,
    OverlayUpdateProjectionInput,
    OverlayValidationProjectionInput,
    SemanticResponseProjector,
)
from app.routers.mcp.create_semantic_overlay import create_semantic_overlay
from app.routers.mcp.update_semantic_overlay import update_semantic_overlay
from app.routers.mcp.validate_semantic_overlay import (
    _cube_references_from_text,
    _validate_semantic_overlay,
    validate_semantic_overlay,
)

projector = SemanticResponseProjector()


OVERLAY_CONTENT = """
cubes:
- name: customer_success_sheet
  description: Customer success records.
  sql_table: '\"customers\".\"customer_success\"'
  meta:
    settra:
      purpose: Track customer success health.
      requirement: Show customer health by owner.
      grain: One row per customer.
      assumptions:
      - Customer id is unique.
      evidence:
      - source: customers.customer_success
  measures:
  - name: customers
    type: count
""".lstrip()

OVERLAY_WITH_CTE_ALIAS = """
cubes:
- name: renewal_model
  sql: |
    WITH ch AS (
      SELECT customer_id, amount
      FROM "sales_sheet"."orders"
    )
    SELECT ch.customer_id, ch.amount
    FROM ch
  meta:
    settra:
      purpose: Validate SQL aliases.
      requirement: Validate CTE aliases.
      grain: One row per charge.
      assumptions:
      - CTE alias ch is internal SQL.
      evidence:
      - source: Sales worksheet sample.
  measures:
  - name: rows
    type: count
    description: Count rows.
  dimensions:
  - name: customer_id
    sql: customer_id
    type: string
    primary_key: true
""".lstrip()


def _complete_manifest():
    return {
        "status": "complete",
        "models": [
            {
                "name": "customer_success_sheet",
                "missing_manifest_fields": [],
            }
        ],
    }


def _compiled_status():
    return {
        "connected": True,
        "compiled": True,
        "cube_count": 10,
        "missing_names": [],
        "compiler_id": "compiler-1",
        "error": None,
    }


class OverlayMutationProjectionTests(unittest.TestCase):
    def test_create_success_is_compact(self):
        result = projector.overlay_create(
            OverlayCreateProjectionInput(
                created=True,
                path="overlays/generated/customer_success_sheet_test.yaml",
                model_names=["customer_success_sheet"],
                manifest=_complete_manifest(),
                compile_status=_compiled_status(),
            )
        )

        self.assertEqual(
            {
                "created": True,
                "path": "overlays/generated/customer_success_sheet_test.yaml",
                "models": ["customer_success_sheet"],
                "manifest_status": "complete",
                "compile_status": "compiled",
                "warnings": [],
            },
            result,
        )
        self.assertNotIn("manifest", result)
        self.assertNotIn("compiler", result)

    def test_create_failure_keeps_compiler_diagnostics(self):
        compile_status = {
            "connected": False,
            "compiled": False,
            "missing_names": ["customer_success_sheet"],
            "compiler_id": None,
            "error": "Cube unavailable",
        }

        result = projector.overlay_create(
            OverlayCreateProjectionInput(
                created=True,
                path="overlays/generated/customer_success_sheet_test.yaml",
                model_names=["customer_success_sheet"],
                manifest=_complete_manifest(),
                compile_status=compile_status,
            )
        )

        self.assertEqual("unavailable", result["compile_status"])
        self.assertNotIn("compiler_id", result["compiler"])
        self.assertEqual("Cube unavailable", result["compiler"]["error"])
        self.assertEqual("COMPILE_INCOMPLETE", result["warnings"][0]["code"])

    def test_update_returns_diff_summary_and_full_diff_is_opt_in(self):
        diff = "\n".join(
            [
                "--- overlay.yaml",
                "+++ overlay.yaml",
                "@@ -1,2 +1,3 @@",
                " old",
                "-description: Old",
                "+description: New",
                "+title: Customers",
            ]
        )
        value = OverlayUpdateProjectionInput(
            updated=True,
            path="overlays/generated/customer_success_sheet_test.yaml",
            models_added=[],
            models_changed=["customer_success_sheet"],
            models_removed=[],
            compile_status=_compiled_status(),
            diff=diff,
        )

        result = projector.overlay_update(value)

        self.assertEqual({"lines_added": 2, "lines_removed": 1}, result["diff_summary"])
        self.assertEqual(["customer_success_sheet"], result["models_changed"])
        self.assertNotIn("diff", result)
        self.assertNotIn("compiler", result)

        verbose = projector.overlay_update(
            OverlayUpdateProjectionInput(**{**value.__dict__, "include_diff": True})
        )
        self.assertEqual(diff, verbose["diff"])


class OverlayValidationProjectionTests(unittest.TestCase):
    def test_success_is_compact(self):
        raw = {
            "valid": True,
            "ready_to_save": True,
            "compiles": True,
            "proposed_path": "overlays/generated/customer_success_sheet_test.yaml",
            "declared_cubes": ["customer_success_sheet"],
            "referenced_cubes": ["customers"],
            "queried_cubes": ["customer_success_sheet"],
            "grain": "One row per customer.",
            "manifest": _complete_manifest(),
            "warnings": [],
            "errors": [],
            "evidence": {"test_query_count": 1},
            "cube": _compiled_status(),
            "cleanup": {"attempted": True, "removed": True, "error": None},
            "test_queries": [
                {
                    "description": "Customer sample",
                    "success": True,
                    "row_count": 10,
                    "error": None,
                }
            ],
        }

        result = projector.overlay_validation(
            OverlayValidationProjectionInput(result=raw)
        )

        self.assertEqual(
            {
                "valid": True,
                "ready_to_save": True,
                "models": ["customer_success_sheet"],
                "compile_status": "compiled",
                "manifest_status": "complete",
                "test_results": [{"success": True, "row_count": 10}],
                "warnings": [],
            },
            result,
        )
        self.assertNotIn("compiler", result)
        self.assertNotIn("cleanup", result)
        self.assertNotIn("evidence", result)

    def test_failure_keeps_diagnostics_and_failed_test_detail(self):
        compiler = {
            "connected": True,
            "compiled": False,
            "missing_names": ["customer_success_sheet"],
            "error": "Unknown member",
        }
        raw = {
            "valid": False,
            "ready_to_save": False,
            "compiles": False,
            "proposed_path": "overlays/generated/customer_success_sheet_test.yaml",
            "declared_cubes": ["customer_success_sheet"],
            "referenced_cubes": ["customers"],
            "queried_cubes": [],
            "grain": "One row per customer.",
            "manifest": {
                "status": "partial",
                "models": [{"missing_manifest_fields": ["evidence", "assumptions"]}],
            },
            "warnings": [{"code": "INCOMPLETE_PROVENANCE_MANIFEST"}],
            "errors": [{"code": "COMPILE_FAILED", "message": "Compile failed"}],
            "evidence": {"test_query_count": 1},
            "cube": compiler,
            "cleanup": {
                "attempted": True,
                "removed": False,
                "error": "Cleanup failed",
            },
            "test_queries": [
                {
                    "description": "Customer sample",
                    "success": False,
                    "row_count": 0,
                    "error": "Unknown member",
                }
            ],
        }

        result = projector.overlay_validation(
            OverlayValidationProjectionInput(result=raw)
        )

        self.assertEqual("not_compiled", result["compile_status"])
        self.assertEqual(compiler, result["compiler"])
        self.assertEqual(raw["cleanup"], result["cleanup"])
        self.assertEqual(["assumptions", "evidence"], result["missing_manifest_fields"])
        self.assertEqual("Unknown member", result["test_results"][0]["error"])
        self.assertIn("diagnostics", result)

    def test_precompile_failure_omits_empty_compiler_and_cleanup_defaults(self):
        raw = {
            "valid": False,
            "ready_to_save": False,
            "compiles": False,
            "proposed_path": None,
            "declared_cubes": [],
            "referenced_cubes": [],
            "queried_cubes": [],
            "grain": None,
            "manifest": {"status": "missing", "models": []},
            "warnings": [],
            "errors": [{"code": "INVALID_YAML", "message": "Invalid YAML"}],
            "evidence": {"test_query_count": 0},
            "cube": {
                "connected": False,
                "compiled": False,
                "cube_count": 0,
                "missing_names": [],
                "compiler_id": None,
                "error": None,
            },
            "cleanup": {
                "attempted": False,
                "removed": False,
                "error": None,
            },
            "test_queries": [],
        }

        result = projector.overlay_validation(
            OverlayValidationProjectionInput(result=raw)
        )

        self.assertEqual("not_run", result["compile_status"])
        self.assertNotIn("compiler", result)
        self.assertNotIn("cleanup", result)


class OverlayMutationToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_tool_projects_the_file_and_compile_results(self):
        with (
            patch(
                "app.routers.mcp.create_semantic_overlay.create_model_file",
                return_value={
                    "ok": True,
                    "created": True,
                    "file": {
                        "path": "overlays/generated/customer_success_sheet_test.yaml",
                        "cube_names": ["customer_success_sheet"],
                        "view_names": [],
                    },
                },
            ),
            patch(
                "app.routers.mcp.create_semantic_overlay.wait_for_compiled_model_names",
                new=AsyncMock(return_value=_compiled_status()),
            ),
        ):
            result = await create_semantic_overlay(
                "customer_success_sheet_test.yaml", OVERLAY_CONTENT
            )

        self.assertTrue(result["created"])
        self.assertEqual("compiled", result["compile_status"])
        self.assertNotIn("file", result)
        self.assertNotIn("manifest", result)
        self.assertNotIn("cube", result)

    async def test_update_tool_only_returns_full_diff_when_requested(self):
        updated_content = OVERLAY_CONTENT.replace(
            "Customer success records.", "Governed customer success records."
        )
        update_result = {
            "ok": True,
            "updated": True,
            "file": {
                "path": "overlays/generated/customer_success_sheet_test.yaml",
                "cube_names": ["customer_success_sheet"],
                "view_names": [],
            },
            "previous_content": OVERLAY_CONTENT,
        }

        with (
            patch(
                "app.routers.mcp.update_semantic_overlay.update_model_file",
                side_effect=lambda *_: {**update_result},
            ),
            patch(
                "app.routers.mcp.update_semantic_overlay.wait_for_compiled_model_names",
                new=AsyncMock(return_value=_compiled_status()),
            ),
        ):
            compact = await update_semantic_overlay(
                "customer_success_sheet_test.yaml", updated_content
            )

        self.assertEqual(["customer_success_sheet"], compact["models_changed"])
        self.assertNotIn("diff", compact)
        self.assertEqual(
            {"lines_added": 1, "lines_removed": 1}, compact["diff_summary"]
        )

        with (
            patch(
                "app.routers.mcp.update_semantic_overlay.update_model_file",
                side_effect=lambda *_: {**update_result},
            ),
            patch(
                "app.routers.mcp.update_semantic_overlay.wait_for_compiled_model_names",
                new=AsyncMock(return_value=_compiled_status()),
            ),
        ):
            verbose = await update_semantic_overlay(
                "customer_success_sheet_test.yaml",
                updated_content,
                include_diff=True,
            )

        self.assertIn("diff", verbose)

    async def test_validation_tool_projects_the_internal_result(self):
        raw = {
            "valid": True,
            "ready_to_save": True,
            "compiles": True,
            "proposed_path": "overlays/generated/customer_success_sheet_test.yaml",
            "declared_cubes": ["customer_success_sheet"],
            "referenced_cubes": [],
            "queried_cubes": [],
            "grain": "One row per customer.",
            "manifest": _complete_manifest(),
            "warnings": [],
            "errors": [],
            "evidence": {"test_query_count": 0},
            "cube": _compiled_status(),
            "cleanup": {"attempted": True, "removed": True, "error": None},
            "test_queries": [],
        }

        with patch(
            "app.routers.mcp.validate_semantic_overlay._validate_semantic_overlay",
            new=AsyncMock(return_value=raw),
        ):
            result = await validate_semantic_overlay(OVERLAY_CONTENT)

        self.assertEqual("compiled", result["compile_status"])
        self.assertNotIn("cube", result)
        self.assertNotIn("cleanup", result)
        self.assertNotIn("manifest", result)

    async def test_validation_duplicate_names_explain_existing_path_for_updates(self):
        with (
            patch(
                "app.routers.mcp.validate_semantic_overlay.load_cube_meta",
                new=AsyncMock(
                    return_value={"cubes": [{"name": "customer_success_sheet"}]}
                ),
            ),
            patch(
                "app.routers.mcp.validate_semantic_overlay.source_definition_index",
                return_value={
                    "customer_success_sheet": {
                        "path": "overlays/generated/customer_success_sheet_test.yaml"
                    }
                },
            ),
        ):
            result = await _validate_semantic_overlay(
                content=OVERLAY_CONTENT,
                path="generated/validation.yaml",
                test_queries=[],
            )

        duplicate = next(
            error
            for error in result["errors"]
            if error["code"] == "DUPLICATE_MODEL_NAME"
        )

        self.assertIn(
            "path='overlays/generated/customer_success_sheet_test.yaml'",
            duplicate["message"],
        )

    async def test_validation_ignores_sql_cte_alias_member_access(self):
        with (
            patch(
                "app.routers.mcp.validate_semantic_overlay.load_cube_meta",
                new=AsyncMock(return_value={"cubes": [], "compilerId": "compiler-1"}),
            ),
            patch(
                "app.routers.mcp.validate_semantic_overlay.source_definition_index",
                return_value={},
            ),
            patch(
                "app.routers.mcp.validate_semantic_overlay.save_model_file",
                return_value={
                    "ok": True,
                    "file": {
                        "path": "overlays/generated/validation.yaml",
                        "cube_names": ["renewal_model"],
                        "view_names": [],
                    },
                },
            ),
            patch(
                "app.routers.mcp.validate_semantic_overlay.wait_for_compiled_model_names",
                new=AsyncMock(return_value=_compiled_status()),
            ),
            patch(
                "app.routers.mcp.validate_semantic_overlay.delete_generated_model_file",
                return_value={"ok": True},
            ),
            patch(
                "app.routers.mcp.validate_semantic_overlay.wait_for_removed_model_names",
                new=AsyncMock(return_value={"removed": True}),
            ),
        ):
            result = await _validate_semantic_overlay(
                content=OVERLAY_WITH_CTE_ALIAS,
                path="generated/validation.yaml",
                test_queries=[],
            )

        self.assertTrue(result["valid"])
        self.assertNotIn(
            "UNRESOLVED_CUBE_REFERENCE",
            [warning["code"] for warning in result["warnings"]],
        )

    def test_reference_extractor_ignores_sql_aliases_but_keeps_semantic_refs(self):
        sql = """
        WITH ch AS (
          SELECT customer_id, amount
          FROM "sales_sheet"."orders" AS raw_ch
        )
        SELECT ch.customer_id, raw_ch.amount, {sales_sheet_customers.id}
        FROM ch
        JOIN "sales_sheet"."orders" charge ON charge.customer = ch.customer_id
        """

        references = _cube_references_from_text(sql)

        self.assertNotIn("ch", references)
        self.assertNotIn("raw_ch", references)
        self.assertNotIn("charge", references)
        self.assertIn("sales_sheet_customers", references)


if __name__ == "__main__":
    unittest.main()
