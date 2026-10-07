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
from app.cube.model_generation import render_connection_manifest_model
from app.cube.identifiers import cube_sql_alias
from app.cube.revisions import model_content_revision
from app.errors import (
    InvalidOperationError,
    ResourceConflictError,
    ResourceNotFoundError,
)
from app.semantic.catalog import authored_definition_index
from app.semantic.catalog import allowed_cube_names_for_pipe_ids
from app.semantic.relationships import build_relationship_catalog
from app.semantic.overlays import generated_overlay_path
from app.routers.collections import router
from app.routers.error_handlers import application_error_handler
from app.errors import ApplicationError
from app.semantic.overlay_validation import validate_semantic_overlay_document
from app.routers.mcp.validate_semantic_overlay import validate_semantic_overlay
from app.routers.mcp.create_semantic_overlay import create_semantic_overlay
from app.routers.mcp.update_semantic_overlay import update_semantic_overlay
from app.routers.semantics import put_cube_model_file, SaveCubeModelFileRequest
from app.semantic.overlays import wait_for_compiled_model_names


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
            "app.semantic.overlays.wait_for_compiled_model_names",
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
        self.assertTrue(
            draft["path"].startswith(
                "overlays/generated/organizations/1/collections/1/"
            )
        )
        self.assertTrue(draft["path"].endswith("sales_semantics.yaml"))
        self.assertFalse((self.root / draft["path"]).exists())
        self.assertEqual(
            original, read_model_file("generated/connections/orders.yaml")["content"]
        )
        cubes = yaml.safe_load(draft["content"])["cubes"]
        self.assertEqual(2, len(cubes))
        self.assertEqual(
            ['{CUBE}."customer_id"', '{CUBE}."customer_id"'],
            [
                next(
                    dimension["sql"]
                    for dimension in cube["dimensions"]
                    if dimension["name"] == "customer_id"
                )
                for cube in cubes
            ],
        )
        self.assertTrue(
            next(
                dimension
                for dimension in cubes[0]["dimensions"]
                if dimension["name"] == "order_id"
            )["primary_key"]
        )
        self.assertEqual(
            "Semantic definitions for Sales",
            cubes[0]["meta"]["settra"]["purpose"],
        )

    async def test_existing_legacy_relationship_overlay_is_reused(self):
        legacy_path = collection_overlay_path(1, "relationships.yaml")
        save_model_file(legacy_path, "cubes: []\n")

        draft = await self.draft()

        self.assertEqual(legacy_path, draft["path"])
        self.assertFalse(draft["create"])
        self.assertEqual("cubes: []\n", draft["expected_content"])

    async def test_arbitrary_overlay_filename_is_scoped_to_the_artifact(self):
        model = copy.deepcopy(authored_definition_index()["orders"]["definition"])
        model.setdefault("meta", {}).setdefault("settra", {}).update(
            {
                "purpose": "Test App-scoped persistence.",
                "requirement": "Keep authored models isolated by App.",
                "grain": "One row per order.",
                "assumptions": [],
                "evidence": {"test": "path ownership"},
            }
        )
        content = yaml.safe_dump({"cubes": [model]})
        result = await write_collection_overlay(
            1,
            path="portfolio.yaml",
            content=content,
            create=True,
        )

        self.assertEqual(
            "overlays/generated/organizations/1/collections/1/portfolio.yaml",
            result["file"]["path"],
        )

    async def test_shortened_generated_and_renamed_keys_use_semantic_references(self):
        physical_column = "customer_business_identifier_with_a_very_long_column_name"
        manifest = self.root / "orders.manifest.yaml"
        manifest.write_text(
            yaml.safe_dump(
                {
                    "tables": [
                        {
                            "name": "rows",
                            "columns": [
                                {"name": "order_id", "type": "text"},
                                {"name": physical_column, "type": "text"},
                            ],
                        }
                    ],
                }
            )
        )
        generated = render_connection_manifest_model(
            manifest,
            {
                "id": 1,
                "slug": "orders",
                "storage_key": "orders",
                "name": "Orders",
                "destination_schema": "orders",
            },
        )
        save_model_file("generated/connections/orders.yaml", generated)
        source = yaml.safe_load(generated)["cubes"][0]
        shortened_member = source["dimensions"][1]["name"]
        self.assertNotEqual(physical_column, shortened_member)
        self.assertEqual(len(shortened_member), 48)

        target_file = read_model_file("generated/connections/customers.yaml")
        target_model = yaml.safe_load(target_file["content"])
        for dimension in target_model["cubes"][0]["dimensions"]:
            if dimension["name"] == "customer_id":
                dimension["sql"] = '"CRM Customer ID"'
        save_model_file(target_file["path"], yaml.safe_dump(target_model))

        draft = await self.draft(
            source_cube=source["name"], source_member=shortened_member
        )
        cubes = yaml.safe_load(draft["content"])["cubes"]
        for cube in cubes:
            members = [
                member["name"]
                for kind in ("dimensions", "measures")
                for member in cube.get(kind, [])
            ]
            self.assertLessEqual(
                len(cube.get("sql_alias", cube["name"])) + 2 + max(map(len, members)),
                63,
            )
        self.assertEqual(13, len(cubes[0]["sql_alias"]))
        self.assertEqual(
            f"{{CUBE.{shortened_member}}} = {{{cubes[1]['name']}.customer_id}}",
            cubes[0]["joins"][0]["sql"],
        )
        catalog = build_relationship_catalog(
            allowed_names={cube["name"] for cube in cubes},
            compiled_names={cube["name"] for cube in cubes},
            definitions={
                cube["name"]: {"definition": cube, "path": draft["path"]}
                for cube in cubes
            },
        )
        relationship = catalog["relationships"][0]
        self.assertTrue(catalog["valid"])
        self.assertEqual(shortened_member, relationship["source_member"])
        self.assertEqual(physical_column, relationship["source_column"])
        self.assertEqual("CRM Customer ID", relationship["target_column"])
        self.assertEqual(
            generated, read_model_file("generated/connections/orders.yaml")["content"]
        )

    async def test_long_measures_are_included_in_model_copy_alias_budget(self):
        source_file = read_model_file("generated/connections/orders.yaml")
        document = yaml.safe_load(source_file["content"])
        long_measure = "a" * 48
        document["cubes"][0]["measures"].append({"name": long_measure, "type": "count"})
        save_model_file(source_file["path"], yaml.safe_dump(document))
        first = await self.draft()
        second = await self.draft()
        first_model = yaml.safe_load(first["content"])["cubes"][0]
        second_model = yaml.safe_load(second["content"])["cubes"][0]
        self.assertEqual(13, len(first_model["sql_alias"]))
        self.assertEqual(first_model["sql_alias"], second_model["sql_alias"])
        self.assertEqual(
            cube_sql_alias(first_model["name"], ["order_id", long_measure]),
            first_model["sql_alias"],
        )
        self.assertEqual(long_measure, first_model["measures"][-1]["name"])

    async def test_other_authored_models_keep_their_custom_sql_aliases(self):
        first = await self.draft()
        document = yaml.safe_load(first["content"])
        target = document["cubes"][1]
        target["name"] = "custom_customers"
        target["meta"]["settra"].pop("source_cube")
        target["sql_alias"] = "my_custom_alias"
        document["cubes"][0]["joins"][0]["name"] = target["name"]
        document["cubes"][0]["joins"][0][
            "sql"
        ] = "{CUBE.customer_id} = {custom_customers.customer_id}"
        save_model_file(first["path"], yaml.safe_dump(document))
        source_name = document["cubes"][0]["name"]
        edited = await self.draft(
            source_cube=source_name,
            target_cube=target["name"],
            existing_id=f"{source_name}:{target['name']}",
        )
        self.assertEqual(target, yaml.safe_load(edited["content"])["cubes"][1])

    async def test_editing_invalid_join_replaces_expression_without_changing_models(
        self,
    ):
        draft = await self.draft()
        document = yaml.safe_load(draft["content"])
        source, target = document["cubes"]
        source["joins"][0][
            "sql"
        ] = f"{{CUBE}}.customer_id = {{{target['name']}}}.customer_id"
        for model, physical_column in (
            (source, "billing_customer_identifier"),
            (target, "CRM Customer ID"),
        ):
            for dimension in model["dimensions"]:
                if dimension["name"] == "customer_id":
                    dimension["sql"] = f'"{physical_column}"'
        save_model_file(draft["path"], yaml.safe_dump(document))

        repaired = await self.draft(
            source_cube=source["name"],
            target_cube=target["name"],
            existing_id=f"{source['name']}:{target['name']}",
        )
        repaired_models = yaml.safe_load(repaired["content"])["cubes"]
        self.assertEqual(target, repaired_models[1])
        self.assertEqual(source["dimensions"], repaired_models[0]["dimensions"])
        self.assertEqual(source["measures"], repaired_models[0]["measures"])
        self.assertEqual(
            f"{{CUBE.customer_id}} = {{{target['name']}.customer_id}}",
            repaired_models[0]["joins"][0]["sql"],
        )
        self.assertEqual(yaml.safe_dump(document), repaired["expected_content"])

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
            with (
                self.subTest(overrides=overrides),
                self.assertRaises(InvalidOperationError),
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

    async def test_all_update_adapters_confirm_exact_content_instead_of_cached_names(
        self,
    ):
        first = await self.draft()
        models = yaml.safe_load(first["content"])["cubes"]
        names = {model["name"] for model in models}
        saved_content = first["content"]

        async def organization_file(path):
            return read_model_file(path)

        async def save(adapter, content, expected):
            if adapter == "collection":
                return await write_collection_overlay(
                    1,
                    path=first["path"],
                    content=content,
                    create=False,
                    expected_content=expected,
                )
            if adapter == "global_http":
                return await put_cube_model_file(
                    first["path"],
                    SaveCubeModelFileRequest(
                        content=content, expected_content=expected
                    ),
                )
            return await update_semantic_overlay(
                "sales", first["path"], content, expected
            )

        def metadata(content):
            return {
                "compilerId": "unchanged",
                "cubes": [
                    {
                        "name": name,
                        "meta": {
                            "settra": {
                                "compiled_model_revision": model_content_revision(
                                    content
                                )
                            }
                        },
                    }
                    for name in names
                ],
            }

        with (
            patch("app.semantic.overlays.SEMANTIC_OVERLAY_COMPILE_ATTEMPTS", 1),
            patch(
                "app.semantic.overlays.wait_for_compiled_model_names",
                wait_for_compiled_model_names,
            ),
            patch(
                "app.routers.semantics._organization_model_file",
                side_effect=organization_file,
            ),
            patch(
                "app.routers.semantics.validate_overlay_for_organization",
                new_callable=AsyncMock,
            ),
            patch(
                "app.routers.mcp.update_semantic_overlay.artifact_context",
                new=AsyncMock(return_value={"id": 1, "cube_names": sorted(names)}),
            ),
        ):
            with patch(
                "app.semantic.overlays.load_cube_meta",
                new=AsyncMock(return_value=metadata("previous_validation")),
            ):
                created = await self.persist(first)
            self.assertTrue(created["created"])
            self.assertFalse(created["cube"]["compiled"])
            for adapter in ("collection", "global_http", "mcp"):
                with self.subTest(adapter=adapter):
                    submitted = saved_content + f"\n# Revision from {adapter}\n"
                    with patch(
                        "app.semantic.overlays.load_cube_meta",
                        new=AsyncMock(return_value=metadata(saved_content)),
                    ):
                        result = await save(adapter, submitted, saved_content)
                    if adapter == "mcp":
                        self.assertEqual("not_compiled", result["compile_status"])
                        self.assertIn("revision", result["compiler"]["error"])
                    else:
                        self.assertFalse(result["cube"]["compiled"])
                        self.assertIn("revision", result["cube"]["error"])
                    self.assertEqual(
                        submitted, read_model_file(first["path"])["content"]
                    )
                    # Identical content is already proven; no compiler ID
                    # change or unnecessary rewrite needs to be invented.
                    with patch(
                        "app.semantic.overlays.load_cube_meta",
                        new=AsyncMock(return_value=metadata(submitted)),
                    ):
                        confirmed = await save(adapter, submitted, submitted)
                    if adapter == "mcp":
                        self.assertEqual("compiled", confirmed["compile_status"])
                    else:
                        self.assertTrue(confirmed["cube"]["compiled"])
                    saved_content = submitted

    async def test_mcp_creation_cannot_accept_cached_names_from_a_previous_validation(
        self,
    ):
        draft = await self.draft()
        model = yaml.safe_load(draft["content"])["cubes"][0]
        model["name"] = "agent_order_model"
        model.pop("joins")
        content = yaml.safe_dump({"cubes": [model]})
        meta = {
            "cubes": [
                {
                    "name": model["name"],
                    "meta": {
                        "settra": {"compiled_model_revision": "previous_validation"}
                    },
                }
            ]
        }
        with (
            patch("app.semantic.overlays.SEMANTIC_OVERLAY_COMPILE_ATTEMPTS", 1),
            patch(
                "app.semantic.overlays.wait_for_compiled_model_names",
                wait_for_compiled_model_names,
            ),
            patch(
                "app.semantic.overlays.load_cube_meta", new=AsyncMock(return_value=meta)
            ),
            patch(
                "app.routers.mcp.create_semantic_overlay.artifact_context",
                new=AsyncMock(return_value={"id": 1}),
            ),
        ):
            result = await create_semantic_overlay(
                "sales", "agent_orders.yaml", content
            )
        self.assertTrue(result["created"])
        self.assertEqual("not_compiled", result["compile_status"])
        self.assertIn("revision", result["compiler"]["error"])
        self.assertEqual(
            content,
            read_model_file(collection_overlay_path(1, "agent_orders.yaml"))["content"],
        )

    def client(self):
        app = FastAPI()
        app.add_exception_handler(ApplicationError, application_error_handler)
        app.include_router(router, prefix="/api")
        return TestClient(app)

    async def test_api_sampling_limits_and_membership_are_checked_before_loading(self):
        with (
            self.client() as client,
            patch(
                "app.routers.collections.get_collection",
                new=AsyncMock(return_value={"slug": "sales"}),
            ),
            patch(
                "app.routers.collections.require_pipe_in_collection",
                new=AsyncMock(
                    side_effect=ResourceNotFoundError("Pipe not in collection")
                ),
            ),
            patch(
                "app.routers.collections.sample_connection_table",
                new_callable=AsyncMock,
            ) as sample,
        ):
            self.assertEqual(
                422,
                client.post(
                    "/api/artifacts/1/pipes/2/tables/rows/sample", json={"limit": 51}
                ).status_code,
            )
            self.assertEqual(
                422,
                client.post(
                    "/api/artifacts/1/pipes/2/tables/rows/profile",
                    json={"limit": 501},
                ).status_code,
            )
            self.assertEqual(
                404,
                client.post(
                    "/api/artifacts/1/pipes/2/tables/rows/sample", json={"limit": 5}
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
                        f"/api/artifacts/1/{suffix}",
                        json={"path": "test.yaml", "content": "cubes: []"},
                    )
                    self.assertEqual(403, response.status_code)
        finally:
            reset_current_identity(token)

    async def test_api_validation_never_replaces_another_collections_model(self):
        first = await self.draft()
        await self.persist(first)
        with (
            self.client() as client,
            patch(
                "app.routers.collections.get_collection",
                new=AsyncMock(return_value={"slug": "other"}),
            ),
            patch(
                "app.semantic.overlay_validation.require_collection",
                new=AsyncMock(return_value={"id": 2, "cube_names": ["orders"]}),
            ),
            patch(
                "app.semantic.overlay_validation.save_model_file",
            ) as save,
        ):
            response = client.post("/api/artifacts/2/overlays/validate", json=first)
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
            "id": 2,
            "slug": "orders_only",
            "pipe_ids": [1],
            "cube_names": ["orders"],
            "pipes": [{"destination_schema": "orders"}],
        }
        with (
            patch(
                "app.collection_service.get_collection",
                new=AsyncMock(return_value=context),
            ),
            patch(
                "app.semantic.overlay_validation._validate_semantic_overlay",
                new_callable=AsyncMock,
            ) as compile_overlay,
        ):
            with self.assertRaises(ResourceNotFoundError):
                await validate_semantic_overlay_document(
                    collection="orders_only", content=content, path=first["path"]
                )
            with self.assertRaisesRegex(ValueError, "not found in artifact"):
                await validate_semantic_overlay(
                    artifact="orders_only", content=content, path=first["path"]
                )
            compile_overlay.assert_not_awaited()
        self.assertEqual(first["content"], read_model_file(first["path"])["content"])

    async def test_shared_validation_allows_new_and_in_scope_replacements(self):
        first = await self.draft()
        await self.persist(first)
        context = {
            "id": 1,
            "slug": "sales",
            "cube_names": list(authored_definition_index()),
        }
        with (
            patch(
                "app.semantic.overlay_validation.require_collection",
                new=AsyncMock(return_value=context),
            ),
            patch(
                "app.semantic.overlay_validation.validate_overlay_for_collection",
                new=AsyncMock(return_value=set()),
            ),
            patch(
                "app.semantic.overlay_validation.validate_queries_for_collection",
                new=AsyncMock(),
            ),
            patch(
                "app.semantic.overlay_validation._validate_semantic_overlay",
                new=AsyncMock(return_value={"valid": True}),
            ) as compile_overlay,
        ):
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
            "id": 1,
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
            with (
                self.subTest(edit=edit),
                patch(
                    "app.collection_service.require_collection",
                    new=AsyncMock(return_value=context),
                ),
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
                collection_overlay_path(1, path)


if __name__ == "__main__":
    unittest.main()
