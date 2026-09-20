import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

import yaml

from app.auth import Identity, reset_current_identity, set_current_identity
from app.collection_build_service import (
    attach_collection_overlay,
    collection_model_file,
    collection_models,
    collection_semantic_coverage,
    remove_collection_overlay,
    write_collection_overlay,
)
from app.collection_service import (
    collection_overlay_prefix,
    delete_collection,
    get_collection,
    require_model_file_in_collection,
)
from app.cube.client import CubeAPIError
from app.cube.model import model_repository, read_model_file, save_model_file
from app.cube.revisions import model_content_revision
from app.errors import InvalidOperationError, ResourceNotFoundError
from app.semantic.catalog import allowed_cube_names_for_pipe_ids
from app.semantic.overlays import get_overlay_detail, list_overlay_details
from app.semantic.query import validate_cube_query_names


def physical(name, pipe_id):
    return {
        "name": name,
        "sql_table": f'"source_{pipe_id}"."rows"',
        "meta": {"settra": {"connection_id": pipe_id}},
        "dimensions": [{"name": "id", "sql": '"id"', "type": "string"}],
        "measures": [{"name": "total", "sql": '"amount"', "type": "sum"}],
        "segments": [{"name": "active", "sql": "{CUBE.id} IS NOT NULL"}],
    }


class CollectionSemanticsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        token = set_current_identity(
            Identity(
                user_id=1,
                organization_id=1,
                email="owner@example.com",
                display_name="Owner",
                organization_name="Workspace",
                organization_slug="workspace",
                organization_kind="personal",
                role="owner",
            )
        )
        self.addCleanup(reset_current_identity, token)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.pipes = {1: "source_1"}
        self.collection = {
            "id": 7,
            "name": "Sales",
            "slug": "sales",
            "cube_names": ["orders"],
        }
        for replacement in (
            patch("app.cube.model.CUBE_MODEL_DIR", self.root),
            patch(
                "app.collection_build_service.get_collection", side_effect=self.context
            ),
            patch(
                "app.semantic.catalog.load_cube_meta",
                new=AsyncMock(return_value={"cubes": []}),
            ),
            patch(
                "app.semantic.overlays.load_cube_meta",
                new=AsyncMock(return_value={"cubes": []}),
            ),
        ):
            replacement.start()
            self.addCleanup(replacement.stop)
        self.save("generated/connections/orders.yaml", cubes=[physical("orders", 1)])
        self.save(
            "generated/connections/customers.yaml", cubes=[physical("customers", 2)]
        )

    async def context(self, _identifier):
        names = allowed_cube_names_for_pipe_ids(
            set(self.pipes),
            pipe_namespaces=self.pipes,
            owned_prefix=collection_overlay_prefix(int(_identifier)),
        )
        return {**self.collection, "cube_names": sorted(names)}

    def save(self, path, *, cubes=(), views=()):
        return save_model_file(
            path,
            yaml.safe_dump(
                {"cubes": list(cubes), "views": list(views)}, sort_keys=False
            ),
        )

    async def test_shared_file_keeps_every_in_scope_cube_view_and_derived_model(self):
        path = "overlays/shared.yaml"
        self.save(
            path,
            cubes=[
                physical("order_metrics", 1),
                physical("customer_metrics", 2),
                {
                    "name": "derived_orders",
                    "extends": "order_metrics",
                },
            ],
            views=[
                {
                    "name": "order_report",
                    "cubes": [{"join_path": "derived_orders", "includes": "*"}],
                }
            ],
        )
        catalog = await collection_models(7)
        self.assertEqual(
            {"orders", "order_metrics", "derived_orders", "order_report"},
            {model["name"] for model in catalog["models"]},
        )
        file = next(file for file in catalog["files"] if file["path"] == path)
        self.assertTrue(file["partial"])
        self.assertTrue(file["read_only"])
        self.assertNotIn("customer_metrics", str(catalog))
        self.assertNotIn("customers", str(catalog))
        model = next(
            model for model in catalog["models"] if model["name"] == "order_metrics"
        )
        self.assertEqual("order_metrics.total", model["meta"]["measures"][0]["name"])
        self.assertEqual("order_metrics.active", model["meta"]["segments"][0]["name"])
        self.assertIn("order_metrics", catalog["source_definitions"])

    async def test_another_apps_overlay_is_not_visible_or_mutable(
        self,
    ):
        path = collection_overlay_prefix(99) + "shared.yaml"
        self.save(
            path, cubes=[physical("order_metrics", 1), physical("customer_metrics", 2)]
        )
        original = read_model_file(path)["content"]
        with self.assertRaises(ResourceNotFoundError):
            await collection_model_file(7, path)
        with self.assertRaises(ResourceNotFoundError):
            await write_collection_overlay(7, path=path, content=original, create=False)
        with self.assertRaises(ResourceNotFoundError):
            await remove_collection_overlay(7, path)
        self.assertEqual(original, read_model_file(path)["content"])

    async def test_apps_sharing_sources_only_see_their_own_authored_models(self):
        self.save(
            collection_overlay_prefix(7) + "sales.yaml",
            cubes=[physical("sales_metrics", 1)],
        )
        self.save(
            collection_overlay_prefix(8) + "renewals.yaml",
            cubes=[physical("renewal_metrics", 1)],
        )

        sales = await self.context(7)
        renewals = await self.context(8)

        self.assertEqual({"orders", "sales_metrics"}, set(sales["cube_names"]))
        self.assertEqual({"orders", "renewal_metrics"}, set(renewals["cube_names"]))

    async def test_collection_owned_model_is_retained_when_required_source_is_removed(
        self,
    ):
        path = collection_overlay_prefix(7) + "joined.yaml"
        joined = physical("joined_orders", 1)
        joined["joins"] = [
            {
                "name": "customers",
                "relationship": "many_to_one",
                "sql": "{CUBE.id} = {customers.id}",
            }
        ]
        self.save(path, cubes=[joined])
        catalog = await collection_models(7)
        model = next(
            model for model in catalog["models"] if model["name"] == "joined_orders"
        )
        self.assertFalse(model["in_scope"])
        file = next(file for file in catalog["files"] if file["path"] == path)
        self.assertTrue(file["owned"])
        self.assertTrue(file["issues"])
        self.assertFalse(file["read_only"])
        context = await self.context(7)
        require_model_file_in_collection(context, await collection_model_file(7, path))
        with self.assertRaises(ResourceNotFoundError):
            validate_cube_query_names(
                {"measures": ["joined_orders.total"]}, set(context["cube_names"])
            )
        self.pipes[2] = "source_2"
        restored = await collection_models(7)
        self.assertTrue(
            next(
                model
                for model in restored["models"]
                if model["name"] == "joined_orders"
            )["in_scope"]
        )

    async def test_broken_owned_yaml_does_not_erase_healthy_models_and_can_be_repaired(
        self,
    ):
        path = collection_overlay_prefix(7) + "broken.yaml"
        target = model_repository().safe_path(path)
        target.parent.mkdir(parents=True)
        target.write_text("cubes: [invalid\n")
        catalog = await collection_models(7)
        self.assertIn("orders", {model["name"] for model in catalog["models"]})
        broken = next(file for file in catalog["files"] if file["path"] == path)
        self.assertTrue(broken["issues"])
        self.assertFalse(broken["read_only"])
        self.assertEqual(
            "cubes: [invalid\n", (await collection_model_file(7, path))["content"]
        )

    async def test_cached_compilation_cannot_hide_the_current_authored_members(self):
        path = "generated/connections/orders.yaml"
        old = read_model_file(path)["content"]
        current = physical("orders", 1)
        current["measures"].append(
            {"name": "new_metric", "sql": '"amount"', "type": "avg"}
        )
        self.save(path, cubes=[current])
        meta = {
            "cubes": [
                {
                    "name": "orders",
                    "title": "Cached orders",
                    "measures": [],
                    "dimensions": [],
                    "segments": [],
                    "meta": {
                        "settra": {
                            "compiled_model_revision": model_content_revision(old)
                        }
                    },
                }
            ]
        }
        with patch(
            "app.semantic.catalog.load_cube_meta", new=AsyncMock(return_value=meta)
        ):
            model = (await collection_models(7))["models"][0]
        self.assertFalse(model["compile"]["compiled"])
        self.assertIn(
            "orders.new_metric",
            {member["name"] for member in model["meta"]["measures"]},
        )
        meta["cubes"][0]["meta"]["settra"]["compiled_model_revision"] = (
            model_content_revision(read_model_file(path)["content"])
        )
        with patch(
            "app.semantic.catalog.load_cube_meta", new=AsyncMock(return_value=meta)
        ):
            model = (await collection_models(7))["models"][0]
        self.assertTrue(model["compile"]["compiled"])
        self.assertEqual("Cached orders", model["meta"]["title"])

    async def test_cube_outage_keeps_stored_semantics_visible_without_compiler_leaks(
        self,
    ):
        with patch(
            "app.semantic.catalog.load_cube_meta",
            new=AsyncMock(side_effect=CubeAPIError("foreign_secret_model failed")),
        ):
            catalog = await collection_models(7)
        self.assertEqual(["orders"], [model["name"] for model in catalog["models"]])
        self.assertEqual("unknown", catalog["models"][0]["compile"]["status"])
        self.assertNotIn("foreign_secret_model", str(catalog))

    async def test_same_source_models_follow_membership_in_each_collection(self):
        row = {"id": 7, "name": "Sales", "slug": "sales"}
        pipe = {
            "id": 1,
            "name": "Orders",
            "slug": "orders",
            "destination_schema": "source_1",
        }
        with patch(
            "app.collection_service._collection_and_pipes",
            new=AsyncMock(return_value=(row, [pipe])),
        ):
            first = await get_collection(7)
            second = await get_collection(8)
        self.assertEqual(["orders"], first["cube_names"])
        self.assertEqual(first["cube_names"], second["cube_names"])
        with patch(
            "app.collection_service._collection_and_pipes",
            new=AsyncMock(return_value=(row, [])),
        ):
            self.assertEqual([], (await get_collection(7))["cube_names"])

    async def test_foreign_organization_and_foreign_collection_files_are_not_authorized(
        self,
    ):
        path = "overlays/generated/organizations/2/collections/7/foreign.yaml"
        self.save(path, cubes=[physical("foreign", 2)])
        self.save(
            collection_overlay_prefix(8) + "other.yaml", cubes=[physical("other", 2)]
        )
        catalog = await collection_models(7)
        self.assertNotIn("foreign", str(catalog))
        self.assertNotIn("other.yaml", str(catalog))
        with self.assertRaises(ResourceNotFoundError):
            await collection_model_file(7, path)

    async def test_deleting_collection_cannot_strand_its_authored_models(self):
        self.save(
            collection_overlay_prefix(7) + "model.yaml", cubes=[physical("metric", 1)]
        )
        with patch(
            "app.collection_service.get_collection",
            new=AsyncMock(return_value={"id": 7, "calculation_count": 0}),
        ):
            with self.assertRaisesRegex(
                InvalidOperationError, "authored semantic models"
            ):
                await delete_collection(7)

    async def coverage(self):
        @asynccontextmanager
        async def database():
            yield type(
                "Database",
                (),
                {
                    "fetch": AsyncMock(
                        return_value=[
                            {
                                "id": 1,
                                "name": "Orders",
                                "destination_schema": "source_1",
                            },
                            {
                                "id": 2,
                                "name": "Customers",
                                "destination_schema": "source_2",
                            },
                        ]
                    )
                },
            )()

        with (
            patch(
                "app.collection_build_service.list_collections",
                new=AsyncMock(return_value=[self.collection]),
            ),
            patch(
                "app.collection_build_service.organization_cube_names",
                new=AsyncMock(return_value={"orders", "customers"}),
            ),
            patch("app.collection_build_service.db_connection", database),
        ):
            return await collection_semantic_coverage()

    async def test_unassigned_source_and_legacy_overlays_have_a_recovery_path(self):
        path = "overlays/generated/organizations/1/legacy.yaml"
        self.save(
            path,
            views=[
                {
                    "name": "legacy_report",
                    "cubes": [{"join_path": "orders.customers", "includes": "*"}],
                }
            ],
        )
        self.save(
            collection_overlay_prefix(7) + "owned.yaml",
            cubes=[physical("owned_customer", 2)],
        )
        self.save(
            "overlays/generated/organizations/2/foreign.yaml",
            cubes=[physical("foreign", 2)],
        )
        coverage = await self.coverage()
        legacy = next(file for file in coverage["unassigned"] if file["path"] == path)
        self.assertEqual([1, 2], legacy["pipe_ids"])
        self.assertEqual(["Orders", "Customers"], legacy["source_names"])
        self.assertTrue(legacy["can_attach"])
        self.assertIn(
            "generated/connections/customers.yaml",
            [file["path"] for file in coverage["unassigned"]],
        )
        self.assertNotIn("foreign.yaml", str(coverage))
        self.assertNotIn("owned.yaml", str(coverage))

    async def test_attachment_preserves_exact_yaml_and_names_then_keeps_it_in_collection(
        self,
    ):
        path = "overlays/generated/organizations/1/legacy.yaml"
        self.save(path, cubes=[physical("legacy_customers", 2)])
        original = read_model_file(path)["content"]
        with patch(
            "app.collection_build_service.collection_semantic_coverage",
            new=AsyncMock(return_value=await self.coverage()),
        ):
            result = await attach_collection_overlay(7, path)
        self.assertEqual(original, result["file"]["content"])
        self.assertEqual(["legacy_customers"], result["file"]["cube_names"])
        self.assertTrue(result["file"]["path"].startswith(collection_overlay_prefix(7)))
        self.assertFalse(model_repository().safe_path(path).exists())
        model = next(
            model
            for model in (await collection_models(7))["models"]
            if model["name"] == "legacy_customers"
        )
        self.assertFalse(model["in_scope"])
        self.assertNotIn(
            result["file"]["path"],
            [file["path"] for file in (await self.coverage())["unassigned"]],
        )
        with patch(
            "app.collection_build_service.collection_semantic_coverage",
            new=AsyncMock(return_value={"unassigned": []}),
        ):
            with self.assertRaises(ResourceNotFoundError):
                await attach_collection_overlay(7, result["file"]["path"])

    async def test_mcp_overlay_discovery_retains_owned_models_with_missing_sources(
        self,
    ):
        path = collection_overlay_prefix(7) + "missing_source.yaml"
        self.save(path, cubes=[physical("retained", 2)])
        listing = await list_overlay_details(
            allowed_names={"orders"}, owned_prefix=collection_overlay_prefix(7)
        )
        self.assertIn("retained", str(listing))
        detail = await get_overlay_detail(
            path, allowed_names={"orders"}, owned_prefix=collection_overlay_prefix(7)
        )
        self.assertIn("retained", str(detail))
        with self.assertRaises(ValueError):
            await get_overlay_detail(
                path,
                allowed_names={"orders"},
                owned_prefix=collection_overlay_prefix(8),
            )


if __name__ == "__main__":
    unittest.main()
