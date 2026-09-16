import unittest
from unittest.mock import AsyncMock, patch

from app.cube.client import CubeAPIError
from app.semantic.overlays import (
    get_overlay_detail,
    list_overlay_details,
    wait_for_compiled_model_names,
)


def _metadata(revisions, compiler_id="old"):
    return {
        "compilerId": compiler_id,
        "cubes": [
            {
                "name": name,
                "meta": {"settra": {"compiled_model_revision": revision}},
            }
            for name, revision in revisions.items()
        ],
    }


class OverlayRevisionCompilationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        attempts = patch("app.semantic.overlays.SEMANTIC_OVERLAY_COMPILE_ATTEMPTS", 3)
        attempts.start()
        self.addCleanup(attempts.stop)
        sleep = patch("app.semantic.overlays.asyncio.sleep", new_callable=AsyncMock)
        sleep.start()
        self.addCleanup(sleep.stop)

    async def test_unchanged_names_or_unrelated_reload_cannot_confirm_a_save(self):
        load = AsyncMock(
            side_effect=[
                _metadata({"Orders": "old", "Sales": "old"}),
                _metadata({"Orders": "old", "Sales": "old"}, "unrelated_reload"),
                _metadata(
                    {"Orders": "submitted", "Sales": "submitted"}, "submitted_reload"
                ),
            ]
        )
        with patch("app.semantic.overlays.load_cube_meta", load):
            result = await wait_for_compiled_model_names(
                ["Orders", "Sales"], expected_revision="submitted"
            )
        self.assertTrue(result["compiled"])
        self.assertTrue(result["revision_seen"])
        self.assertEqual(3, load.await_count)

    async def test_every_cube_and_view_must_match_the_saved_revision(self):
        for revisions in (
            {"Orders": "submitted", "SalesView": "old"},
            {"Orders": "submitted", "SalesView": None},
            {"Orders": "old", "SalesView": "old"},
        ):
            with self.subTest(revisions=revisions), patch(
                "app.semantic.overlays.load_cube_meta",
                new=AsyncMock(return_value=_metadata(revisions, "new")),
            ):
                result = await wait_for_compiled_model_names(
                    ["Orders", "SalesView"], expected_revision="submitted"
                )
                self.assertFalse(result["compiled"])
                self.assertEqual([], result["missing_names"])
                self.assertIn("revision", result["error"])
                self.assertIn("SalesView", result["revision_missing_names"])

    async def test_identical_content_or_missing_compiler_id_uses_revision_evidence(
        self,
    ):
        for compiler_id in ("old", None):
            with self.subTest(compiler_id=compiler_id), patch(
                "app.semantic.overlays.load_cube_meta",
                new=AsyncMock(
                    return_value=_metadata({"Orders": "submitted"}, compiler_id)
                ),
            ):
                result = await wait_for_compiled_model_names(
                    ["Orders"], after_compiler_id="old", expected_revision="submitted"
                )
                self.assertTrue(result["compiled"])

    async def test_missing_compiler_id_cannot_prove_an_unmarked_reload(self):
        with patch(
            "app.semantic.overlays.load_cube_meta",
            new=AsyncMock(return_value=_metadata({"Orders": None}, None)),
        ):
            result = await wait_for_compiled_model_names(
                ["Orders"], after_compiler_id="old"
            )
        self.assertFalse(result["compiled"])

    async def test_upstream_failure_preserves_the_compile_error(self):
        with patch(
            "app.semantic.overlays.load_cube_meta",
            new=AsyncMock(
                side_effect=CubeAPIError("Cube is unavailable", status_code=503)
            ),
        ):
            result = await wait_for_compiled_model_names(
                ["Orders"], expected_revision="submitted"
            )
        self.assertFalse(result["compiled"])
        self.assertFalse(result["connected"])
        self.assertEqual("Cube is unavailable", result["error"])

    async def test_overlay_reads_never_label_an_older_or_unmarked_version_compiled(
        self,
    ):
        file = {
            "path": "overlays/generated/orders.yaml",
            "source_type": "generated_overlay",
            "cube_names": ["Orders"],
            "view_names": [],
            "content": "cubes:\n  - name: Orders\n    sql_table: orders.rows\n",
        }
        for revision in ("older_version", None):
            with (
                self.subTest(revision=revision),
                patch(
                    "app.semantic.overlays.read_semantic_overlay_file",
                    return_value=file,
                ),
                patch(
                    "app.semantic.overlays.list_semantic_overlay_files",
                    return_value=[file],
                ),
                patch(
                    "app.semantic.overlays._load_optional_cube_meta",
                    new=AsyncMock(return_value=(_metadata({"Orders": revision}), None)),
                ),
            ):
                detail = await get_overlay_detail("generated/orders.yaml")
                listing = await list_overlay_details("generated")
                self.assertEqual("not_compiled", detail["compile"]["status"])
                self.assertEqual("not_compiled", listing["overlays"][0]["status"])
