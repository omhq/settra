import json
import unittest

from unittest.mock import AsyncMock, patch

from app.cube.projection import (
    OverlayListItemProjectionInput,
    OverlayListProjectionInput,
    OverlayProjectionInput,
    SemanticResponseProjector,
)
from app.routers.mcp.common import get_overlay_detail, list_overlay_details

projector = SemanticResponseProjector()


OVERLAY_CONTENT = """
cubes:
- name: customer_success_sheet
  description: Customer success records.
  sql_table: '"customers"."customer_success"'
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
  dimensions:
  - name: customer_id
    sql: customer_id
    type: string
    primary_key: true
""".lstrip()


class SemanticOverlayProjectionTests(unittest.TestCase):
    def test_returns_yaml_once_with_compact_compile_and_manifest_status(self):
        manifest = {
            "status": "complete",
            "purpose": "Track customer success health.",
            "requirement": "Show customer health by owner.",
            "evidence": [{"source": "customers.customer_success"}],
            "models": [
                {
                    "name": "customer_success_sheet",
                    "type": "cube",
                    "description": "Customer success records.",
                    "manifest": {
                        "purpose": "Track customer success health.",
                        "requirement": "Show customer health by owner.",
                        "grain": "One row per customer.",
                        "assumptions": ["Customer id is unique."],
                        "evidence": [{"source": "customers.customer_success"}],
                    },
                    "manifest_complete": True,
                    "missing_manifest_fields": [],
                }
            ],
        }
        compile_status = {
            "connected": True,
            "status": "compiled",
            "compiled": True,
            "compiled_names": ["customer_success_sheet"],
            "missing_names": [],
            "error": None,
        }

        result = projector.overlay(
            OverlayProjectionInput(
                path="overlays/generated/customer_success_sheet_test.yaml",
                content=OVERLAY_CONTENT,
                model_names=["customer_success_sheet"],
                manifest=manifest,
                compile_status=compile_status,
            )
        )

        self.assertEqual(
            {
                "path": "overlays/generated/customer_success_sheet_test.yaml",
                "content": OVERLAY_CONTENT,
                "compile": {
                    "status": "compiled",
                    "models": ["customer_success_sheet"],
                },
                "manifest": {"status": "complete", "missing_fields": []},
            },
            result,
        )
        serialized = json.dumps(result)
        self.assertEqual(1, serialized.count("Track customer success health."))
        self.assertNotIn("compiled_models", result)

    def test_preserves_missing_fields_models_and_errors_without_expansion(self):
        result = projector.overlay(
            OverlayProjectionInput(
                path="overlays/generated/broken.yaml",
                content="cubes: [",
                model_names=["one", "two"],
                manifest={
                    "status": "partial",
                    "models": [
                        {
                            "name": "one",
                            "missing_manifest_fields": ["evidence", "grain"],
                        },
                        {
                            "name": "two",
                            "missing_manifest_fields": ["grain", "assumptions"],
                        },
                    ],
                },
                compile_status={
                    "status": "partial",
                    "compiled_names": ["one"],
                    "missing_names": ["two"],
                    "error": None,
                },
                parse_error="Invalid overlay YAML",
            )
        )

        self.assertEqual(
            {
                "status": "partial",
                "models": ["one", "two"],
                "compiled_models": ["one"],
                "missing_models": ["two"],
                "error": "Invalid overlay YAML",
            },
            result["compile"],
        )
        self.assertEqual(
            {
                "status": "partial",
                "missing_fields": ["assumptions", "evidence", "grain"],
            },
            result["manifest"],
        )


class SemanticOverlayListProjectionTests(unittest.TestCase):
    def test_returns_one_nonduplicated_summary_per_overlay(self):
        result = projector.overlay_list(
            OverlayListProjectionInput(
                overlays=[
                    OverlayListItemProjectionInput(
                        path=("overlays/generated/" "customer_success_sheet_test.yaml"),
                        model_names=["customer_success_sheet"],
                        manifest={
                            "status": "complete",
                            "purpose": (
                                "Expose the customer-success worksheet as a "
                                "governed renewal model."
                            ),
                            "requirement": "Analyze renewals.",
                            "evidence": [{"source": "customers.sheet"}],
                            "models": [
                                {
                                    "name": "customer_success_sheet",
                                    "manifest": {
                                        "purpose": (
                                            "Expose the customer-success worksheet "
                                            "as a governed renewal model."
                                        ),
                                        "requirement": "Analyze renewals.",
                                        "evidence": [{"source": "customers.sheet"}],
                                    },
                                }
                            ],
                        },
                        compile_status={
                            "status": "compiled",
                            "compiled_names": ["customer_success_sheet"],
                            "missing_names": [],
                            "error": None,
                        },
                    )
                ]
            )
        )

        self.assertEqual(
            {
                "overlays": [
                    {
                        "path": (
                            "overlays/generated/" "customer_success_sheet_test.yaml"
                        ),
                        "models": ["customer_success_sheet"],
                        "status": "compiled",
                        "manifest_status": "complete",
                        "purpose": (
                            "Expose the customer-success worksheet as a "
                            "governed renewal model."
                        ),
                    }
                ],
                "count": 1,
            },
            result,
        )
        serialized = json.dumps(result)
        self.assertEqual(1, serialized.count("governed renewal model"))
        self.assertNotIn("requirement", serialized)
        self.assertNotIn("evidence", serialized)

    def test_preserves_one_compiler_error_without_nested_status_blocks(self):
        result = projector.overlay_list(
            OverlayListProjectionInput(overlays=[], error="Cube unavailable")
        )

        self.assertEqual(
            {"overlays": [], "count": 0, "error": "Cube unavailable"},
            result,
        )


class GetSemanticOverlayTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_overlay_detail_uses_the_compact_projection(self):
        file = {
            "path": "overlays/generated/customer_success_sheet_test.yaml",
            "source_type": "generated_overlay",
            "size": len(OVERLAY_CONTENT),
            "updated_at": "2026-07-05T00:00:00Z",
            "cube_count": 1,
            "view_count": 0,
            "cube_names": ["customer_success_sheet"],
            "view_names": [],
            "content": OVERLAY_CONTENT,
        }
        compiled_cube = {
            "name": "customer_success_sheet",
            "description": "Customer success records.",
            "measures": [{"name": "customer_success_sheet.customers"}],
            "dimensions": [{"name": "customer_success_sheet.customer_id"}],
        }

        with (
            patch(
                "app.routers.mcp.common.read_semantic_overlay_file",
                return_value=file,
            ),
            patch(
                "app.routers.mcp.common._load_optional_cube_meta",
                new=AsyncMock(return_value=({"cubes": [compiled_cube]}, None)),
            ),
        ):
            result = await get_overlay_detail(
                "generated/customer_success_sheet_test.yaml"
            )

        self.assertEqual(OVERLAY_CONTENT, result["content"])
        self.assertEqual("compiled", result["compile"]["status"])
        self.assertEqual("complete", result["manifest"]["status"])
        self.assertNotIn("file", result)
        self.assertNotIn("cube", result)
        self.assertNotIn("compiled_models", result)


class ListSemanticOverlaysTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_overlay_details_uses_compact_summaries(self):
        file = {
            "path": "overlays/generated/customer_success_sheet_test.yaml",
            "source_type": "generated_overlay",
            "size": len(OVERLAY_CONTENT),
            "updated_at": "2026-07-05T00:00:00Z",
            "cube_count": 1,
            "view_count": 0,
            "cube_names": ["customer_success_sheet"],
            "view_names": [],
        }
        detail = {**file, "content": OVERLAY_CONTENT}

        with (
            patch(
                "app.routers.mcp.common.list_semantic_overlay_files",
                return_value=[file],
            ),
            patch(
                "app.routers.mcp.common.read_semantic_overlay_file",
                return_value=detail,
            ),
            patch(
                "app.routers.mcp.common._load_optional_cube_meta",
                new=AsyncMock(
                    return_value=(
                        {"cubes": [{"name": "customer_success_sheet"}]},
                        None,
                    )
                ),
            ),
        ):
            result = await list_overlay_details("generated")

        self.assertEqual(1, result["count"])
        self.assertEqual(
            {
                "path": "overlays/generated/customer_success_sheet_test.yaml",
                "models": ["customer_success_sheet"],
                "status": "compiled",
                "manifest_status": "complete",
                "purpose": "Track customer success health.",
            },
            result["overlays"][0],
        )
        self.assertNotIn("scope", result)
        self.assertNotIn("cube", result)
        self.assertNotIn("manifest", result["overlays"][0])


if __name__ == "__main__":
    unittest.main()
