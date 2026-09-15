import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from dataclasses import replace

from fastapi import FastAPI
from fastapi.testclient import TestClient

import yaml

from app.auth import Identity, reset_current_identity, set_current_identity
from app.collection_build_service import (
    collection_model_file,
    collection_overlay_path,
    relationship_draft,
    write_collection_overlay,
    execute_collection_query,
)
from app.cube.model import read_model_file, save_model_file
from app.errors import (
    InvalidOperationError,
    ResourceConflictError,
    ResourceNotFoundError,
)
from app.semantic.catalog import authored_definition_index
from app.semantic.catalog import allowed_cube_names_for_pipe_ids
from app.semantic.overlays import generated_overlay_path
from app.routers.collections import router
from app.routers.error_handlers import application_error_handler
from app.errors import ApplicationError
from app.semantic.overlay_validation import validate_semantic_overlay_document
from app.routers.mcp.validate_semantic_overlay import validate_semantic_overlay


class CollectionBuildTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        identity = Identity(
            user_id=1,
            organization_id=1,
            email="owner@example.com",
            display_name="Owner",
            organization_name="Workspace",
            organization_slug="workspace",
            organization_kind="personal",
            role="owner",
        )
        token = set_current_identity(identity)
        self.addCleanup(reset_current_identity, token)
        model_root = patch("app.cube.model.CUBE_MODEL_DIR", self.root)
        model_root.start()
        self.addCleanup(model_root.stop)
        for connection_id, name, key in (
            (1, "orders", "order_id"),
            (2, "customers", "customer_id"),
            (3, "regions", "region_id"),
        ):
            dimensions = [
                {"name": member, "sql": f'"{member}"', "type": "string"}
                for member in {key, "customer_id", "region_id"}
            ]
            save_model_file(
                f"generated/connections/{name}.yaml",
                yaml.safe_dump(
                    {
                        "cubes": [
                            {
                                "name": name,
                                "sql_table": f'"{name}"."rows"',
                                "meta": {"settra": {"connection_id": connection_id}},
                                "dimensions": dimensions,
                                "measures": [
                                    {
                                        "name": "row_count",
                                        "type": "count",
                                        "description": "Rows",
                                    }
                                ],
                            }
                        ]
                    }
                ),
            )
        get_collection = patch(
            "app.collection_build_service.get_collection", side_effect=self.collection
        )
        get_collection.start()
        self.addCleanup(get_collection.stop)
        validate = patch(
            "app.collection_build_service.validate_overlay_for_collection",
            new_callable=AsyncMock,
        )
        validate.start()
        self.addCleanup(validate.stop)
        compile_models = patch(
            "app.collection_build_service.wait_for_compiled_model_names",
            new_callable=AsyncMock,
            return_value={"compiled": True},
        )
        compile_models.start()
        self.addCleanup(compile_models.stop)

    async def collection(self, collection_id):
        return {
            "id": collection_id,
            "name": "Sales",
            "slug": "sales",
            "cube_names": list(authored_definition_index()),
        }

    async def draft(self, **overrides):
        fields = {
            "source_cube": "orders",
            "target_cube": "customers",
            "source_member": "customer_id",
            "target_member": "customer_id",
            "source_primary_key": "order_id",
            "target_primary_key": "customer_id",
            "relationship": "many_to_one",
        }
        fields.update(overrides)
        return await relationship_draft(1, **fields)

    async def persist(self, draft):
        return await write_collection_overlay(1, **draft)

    async def test_source_models_are_untouched_and_draft_is_not_persisted(self):
        original = read_model_file("generated/connections/orders.yaml")["content"]
        draft = await self.draft()
        self.assertTrue(draft["create"])
        self.assertFalse((self.root / draft["path"]).exists())
        self.assertEqual(
            original, read_model_file("generated/connections/orders.yaml")["content"]
        )
        cubes = yaml.safe_load(draft["content"])["cubes"]
        self.assertEqual(2, len(cubes))
        self.assertTrue(
            next(
                dimension
                for dimension in cubes[0]["dimensions"]
                if dimension["name"] == "order_id"
            )["primary_key"]
        )

    async def test_subsequent_joins_reuse_models_and_keep_metrics(self):
        first = await self.draft()
        await self.persist(first)
        next_draft = await self.draft(
            target_cube="regions",
            target_member="region_id",
            source_member="region_id",
            target_primary_key="region_id",
        )
        cubes = yaml.safe_load(next_draft["content"])["cubes"]
        self.assertEqual(3, len(cubes))
        self.assertEqual(2, len(cubes[0]["joins"]))
        self.assertEqual("row_count", cubes[0]["measures"][0]["name"])
        self.assertFalse(next_draft["create"])
        self.assertEqual(first["content"], next_draft["expected_content"])

    async def test_relationship_edit_and_removal_preserve_other_joins_and_models(self):
        first = await self.draft()
        await self.persist(first)
        second = await self.draft(
            target_cube="regions",
            target_member="region_id",
            source_member="region_id",
            target_primary_key="region_id",
        )
        await self.persist(second)
        original = yaml.safe_load(second["content"])
        source, target, region = original["cubes"]
        relationship_id = f"{source['name']}:{target['name']}"
        edited = await self.draft(
            source_cube=source["name"],
            target_cube=target["name"],
            relationship="one_to_one",
            source_member="order_id",
            target_member="customer_id",
            existing_id=relationship_id,
        )
        # Both keys are primary, so this is structurally valid.
        edited_models = yaml.safe_load(edited["content"])["cubes"]
        self.assertEqual(3, len(edited_models))
        self.assertEqual(region, edited_models[2])
        await self.persist(edited)
        removed = await self.draft(
            source_cube=source["name"], existing_id=relationship_id, remove=True
        )
        models = yaml.safe_load(removed["content"])["cubes"]
        self.assertEqual(3, len(models))
        self.assertEqual(
            [region["name"]], [join["name"] for join in models[0]["joins"]]
        )
        self.assertEqual(source["measures"], models[0]["measures"])

    async def test_stale_model_save_does_not_overwrite_agent_changes(self):
        draft = await self.draft()
        await self.persist(draft)
        next_draft = await self.draft(
            target_cube="regions",
            target_member="region_id",
            source_member="region_id",
            target_primary_key="region_id",
        )
        agent_content = draft["content"] + "\n# Agent update\n"
        save_model_file(draft["path"], agent_content)
        with self.assertRaises(ResourceConflictError):
            await self.persist(next_draft)
        self.assertEqual(agent_content, read_model_file(draft["path"])["content"])

    async def test_invalid_member_cardinality_and_self_join_are_rejected(self):
        for overrides in (
            {"source_member": "missing"},
            {"relationship": "many_to_many"},
            {"source_cube": "customers"},
            {"target_primary_key": "region_id"},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(
                InvalidOperationError
            ):
                await self.draft(**overrides)

    async def test_duplicate_relationship_cannot_replace_existing_work(self):
        first = await self.draft()
        await self.persist(first)
        with self.assertRaises(ResourceConflictError):
            await self.draft()
        self.assertEqual(first["content"], read_model_file(first["path"])["content"])

    async def test_models_and_relationships_outside_collection_are_not_accessible(self):
        with patch(
            "app.collection_build_service.get_collection",
            new=AsyncMock(
                return_value={
                    "id": 1,
                    "name": "Sales",
                    "slug": "sales",
                    "cube_names": ["orders"],
                }
            ),
        ):
            with self.assertRaises(ResourceNotFoundError):
                await self.draft()
            with self.assertRaises(ResourceNotFoundError):
                await collection_model_file(1, "generated/connections/customers.yaml")

    async def test_readonly_authored_model_cannot_be_modified(self):
        authored = copy.deepcopy(authored_definition_index()["orders"]["definition"])
        authored["name"] = "readonly_orders"
        save_model_file("overlays/orders.yaml", yaml.safe_dump({"cubes": [authored]}))
        with self.assertRaises(InvalidOperationError):
            await self.draft(source_cube="readonly_orders")

    async def test_query_uses_the_same_limits_and_result_projection_as_mcp(self):
        execute = AsyncMock(
            return_value={
                "data": [{"orders.order_id": "O1"}, {"orders.order_id": "O2"}]
            }
        )
        with patch(
            "app.collection_build_service.execute_cube_query_payload", new=execute
        ):
            result = await execute_collection_query(
                1, {"dimensions": ["orders.order_id"], "limit": 1}
            )
        self.assertEqual([{"orders.order_id": "O1"}], result["data"])
        self.assertTrue(result["has_more"])
        self.assertEqual(2, execute.call_args.args[0]["limit"])
        self.assertIn("orders", execute.call_args.kwargs["allowed_names"])
        with self.assertRaises(ApplicationError):
            await execute_collection_query(1, {})

    def client(self):
        app = FastAPI()
        app.add_exception_handler(ApplicationError, application_error_handler)
        app.include_router(router, prefix="/api")
        return TestClient(app)

    async def test_api_sampling_limits_and_membership_are_checked_before_loading(self):
        with self.client() as client, patch(
            "app.routers.collections.get_collection",
            new=AsyncMock(return_value={"slug": "sales"}),
        ), patch(
            "app.routers.collections.require_pipe_in_collection",
            new=AsyncMock(side_effect=ResourceNotFoundError("Pipe not in collection")),
        ), patch(
            "app.routers.collections.sample_connection_table", new_callable=AsyncMock
        ) as sample:
            self.assertEqual(
                422,
                client.post(
                    "/api/collections/1/pipes/2/tables/rows/sample", json={"limit": 51}
                ).status_code,
            )
            self.assertEqual(
                422,
                client.post(
                    "/api/collections/1/pipes/2/tables/rows/profile",
                    json={"limit": 501},
                ).status_code,
            )
            self.assertEqual(
                404,
                client.post(
                    "/api/collections/1/pipes/2/tables/rows/sample", json={"limit": 5}
                ).status_code,
            )
            sample.assert_not_awaited()

    async def test_api_viewer_cannot_validate_or_write_overlay_files(self):
        from app.auth import current_identity

        token = set_current_identity(replace(current_identity(), role="viewer"))
        try:
            with self.client() as client:
                for suffix in ("overlays", "overlays/validate"):
                    response = client.post(
                        f"/api/collections/1/{suffix}",
                        json={"path": "test.yaml", "content": "cubes: []"},
                    )
                    self.assertEqual(403, response.status_code)
        finally:
            reset_current_identity(token)

    async def test_api_validation_never_replaces_another_collections_model(self):
        first = await self.draft()
        await self.persist(first)
        with self.client() as client, patch(
            "app.routers.collections.get_collection",
            new=AsyncMock(return_value={"slug": "other"}),
        ), patch(
            "app.semantic.overlay_validation.require_collection",
            new=AsyncMock(return_value={"cube_names": ["orders"]}),
        ), patch(
            "app.semantic.overlay_validation.save_model_file",
        ) as save:
            response = client.post("/api/collections/2/overlays/validate", json=first)
            self.assertEqual(404, response.status_code)
            save.assert_not_called()
        self.assertEqual(first["content"], read_model_file(first["path"])["content"])

    async def test_shared_and_mcp_validation_authorize_existing_file_before_content(
        self,
    ):
        first = await self.draft()
        await self.persist(first)
        proposed = copy.deepcopy(authored_definition_index()["orders"]["definition"])
        proposed["name"] = "new_orders"
        content = yaml.safe_dump({"cubes": [proposed]})
        context = {
            "slug": "orders_only",
            "pipe_ids": [1],
            "cube_names": ["orders"],
            "pipes": [{"destination_schema": "orders"}],
        }
        with patch(
            "app.collection_service.get_collection", new=AsyncMock(return_value=context)
        ), patch(
            "app.semantic.overlay_validation._validate_semantic_overlay",
            new_callable=AsyncMock,
        ) as compile_overlay:
            with self.assertRaises(ResourceNotFoundError):
                await validate_semantic_overlay_document(
                    collection="orders_only", content=content, path=first["path"]
                )
            with self.assertRaisesRegex(ValueError, "not found in collection"):
                await validate_semantic_overlay(
                    collection="orders_only", content=content, path=first["path"]
                )
            compile_overlay.assert_not_awaited()
        self.assertEqual(first["content"], read_model_file(first["path"])["content"])

    async def test_shared_validation_allows_new_and_in_scope_replacements(self):
        first = await self.draft()
        await self.persist(first)
        context = {"slug": "sales", "cube_names": list(authored_definition_index())}
        with patch(
            "app.semantic.overlay_validation.require_collection",
            new=AsyncMock(return_value=context),
        ), patch(
            "app.semantic.overlay_validation.validate_overlay_for_collection",
            new=AsyncMock(return_value=set()),
        ), patch(
            "app.semantic.overlay_validation.validate_queries_for_collection",
            new=AsyncMock(),
        ), patch(
            "app.semantic.overlay_validation._validate_semantic_overlay",
            new=AsyncMock(return_value={"valid": True}),
        ) as compile_overlay:
            for path in (first["path"], "new.yaml"):
                result = await validate_semantic_overlay_document(
                    collection="sales", content=first["content"], path=path
                )
                self.assertTrue(result["valid"])
            self.assertEqual(2, compile_overlay.await_count)

    async def test_source_provenance_cannot_authorize_a_foreign_join_or_member_expression(
        self,
    ):
        from app.collection_service import validate_overlay_for_collection

        context = {
            "pipe_ids": [1],
            "cube_names": ["orders"],
            "pipes": [{"destination_schema": "orders"}],
        }
        for edit in (
            {
                "joins": [
                    {
                        "name": "customers",
                        "relationship": "many_to_one",
                        "sql": "{CUBE}.customer_id = {customers}.customer_id",
                    }
                ]
            },
            {
                "dimensions": [
                    {
                        "name": "customer_name",
                        "type": "string",
                        "sql": "{customers.customer_name}",
                    }
                ]
            },
        ):
            model = {
                **copy.deepcopy(authored_definition_index()["orders"]["definition"]),
                **edit,
            }
            with self.subTest(edit=edit), patch(
                "app.collection_service.require_collection",
                new=AsyncMock(return_value=context),
            ):
                with self.assertRaises(InvalidOperationError):
                    await validate_overlay_for_collection(
                        "orders_only", yaml.safe_dump({"cubes": [model]})
                    )

    async def test_models_requiring_another_pipe_are_not_visible_in_a_smaller_collection(
        self,
    ):
        draft = await self.draft()
        await self.persist(draft)
        joined_source = yaml.safe_load(draft["content"])["cubes"][0]["name"]
        allowed = allowed_cube_names_for_pipe_ids({1}, pipe_namespaces={1: "orders"})
        self.assertIn("orders", allowed)
        self.assertNotIn(joined_source, allowed)
        self.assertIn(
            joined_source,
            allowed_cube_names_for_pipe_ids(
                {1, 2}, pipe_namespaces={1: "orders", 2: "customers"}
            ),
        )

    def test_traversal_cannot_escape_the_organization_namespace(self):
        for path in (
            "generated/organizations/1/../2/other.yaml",
            "generated/../../organizations/2/other.yaml",
            "generated/organizations/2/other.yaml",
        ):
            with self.subTest(path=path), self.assertRaises(ValueError):
                generated_overlay_path(path)
            with self.assertRaises(InvalidOperationError):
                collection_overlay_path(path)


if __name__ == "__main__":
    unittest.main()
