import unittest

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

from app.routers.mcp import create_app as create_app_module
from app.routers.mcp import delete_app as delete_app_module
from app.routers.mcp import delete_semantic_overlay as delete_overlay_module
from app.routers.mcp import draft_relationship as draft_relationship_module
from app.routers.mcp import execute_calculation as execute_calculation_module
from app.routers.mcp import get_calculation as get_calculation_module
from app.routers.mcp import get_connection_metadata as metadata_module
from app.routers.mcp import list_calculation_parameter_options as options_module
from app.routers.mcp import list_calculations as list_calculations_module
from app.routers.mcp import list_connections as list_connections_module
from app.routers.mcp import list_relationships as list_relationships_module
from app.routers.mcp import manage_calculation as manage_calculation_module
from app.routers.mcp import management as management_module
from app.routers.mcp import preview_dependency_impact as impact_module
from app.routers.mcp import update_app as update_app_module
from app.routers.mcp import validate_calculation as validate_calculation_module
from app.routers.mcp import validate_relationships as validate_relationships_module

APP = {
    "id": 3,
    "name": "Finance",
    "slug": "finance",
    "description": "Finance data",
    "agent_instructions": "Use booked revenue",
    "pipe_ids": [8, 9],
    "pipe_count": 2,
    "cube_count": 4,
    "calculation_count": 1,
}
CALCULATION = {
    "id": 7,
    "name": "Monthly revenue",
    "slug": "monthly_revenue",
    "collection_id": 3,
    "collection_slug": "finance",
    "content": "version: 1\nname: monthly_revenue\nnodes: []\noutputs: {}\n",
}


class MCPAppManagementTests(unittest.IsolatedAsyncioTestCase):
    async def test_shared_write_resolver_authorizes_before_loading_the_app(self):
        with (
            patch.object(
                management_module,
                "require_mcp_write_access",
                side_effect=ValueError("Owner or admin access is required"),
            ),
            patch.object(
                management_module,
                "require_collection",
                new=AsyncMock(),
            ) as require_collection,
        ):
            with self.assertRaisesRegex(ValueError, "Owner or admin"):
                await management_module.app_context("finance", write=True)

        require_collection.assert_not_awaited()

    async def test_connection_discovery_supports_global_and_app_scopes(self):
        class RecordingDatabase:
            calls = []

            async def fetch(self, query, *args):
                self.calls.append((query, args))
                return []

        database = RecordingDatabase()

        @asynccontextmanager
        async def recording_database():
            yield database

        with (
            patch.object(list_connections_module, "db_connection", recording_database),
            patch.object(
                list_connections_module,
                "current_organization_id",
                return_value=41,
            ),
            patch.object(
                list_connections_module,
                "require_collection",
                new=AsyncMock(return_value={"pipe_ids": [8, 9]}),
            ) as require_collection,
        ):
            await list_connections_module.list_connections()
            await list_connections_module.list_connections("finance")

        self.assertNotIn("ANY", database.calls[0][0])
        self.assertEqual(("googledrive", 41), database.calls[0][1])
        self.assertIn("ANY", database.calls[1][0])
        self.assertEqual(("googledrive", [8, 9], 41), database.calls[1][1])
        require_collection.assert_awaited_once_with("finance")

    async def test_source_description_supports_global_and_app_scopes(self):
        metadata = {"connection_id": 8, "tables": [], "page": {"total": 0}}

        with (
            patch.object(
                metadata_module,
                "bounded_connection_metadata",
                new=AsyncMock(return_value=metadata),
            ) as describe,
            patch.object(
                metadata_module,
                "require_pipe_in_collection",
                new=AsyncMock(return_value={}),
            ) as require_pipe,
        ):
            self.assertEqual(
                metadata,
                await metadata_module.get_connection_metadata(8),
            )
            require_pipe.assert_not_awaited()

            self.assertEqual(
                metadata,
                await metadata_module.get_connection_metadata(8, "finance"),
            )

        require_pipe.assert_awaited_once_with("finance", 8)
        self.assertEqual(2, describe.await_count)

    async def test_create_app_delegates_to_the_collection_service(self):
        created = {**APP, "pipe_ids": [8], "pipe_count": 1}

        with (
            patch.object(create_app_module, "require_mcp_write_access") as write,
            patch.object(
                create_app_module,
                "create_collection",
                new=AsyncMock(return_value=created),
            ) as create,
        ):
            result = await create_app_module.create_app(
                "Finance",
                description="Finance data",
                agent_instructions="Use booked revenue",
                pipe_ids=[8],
            )

        write.assert_called_once_with()
        create.assert_awaited_once_with(
            name="Finance",
            description="Finance data",
            agent_instructions="Use booked revenue",
            pipe_ids=[8],
        )
        self.assertEqual("finance", result["slug"])

    async def test_dependency_preview_delegates_to_shared_services(self):
        impact = {"action": "delete_model", "has_impact": True}

        with (
            patch.object(
                impact_module,
                "app_context",
                new=AsyncMock(return_value=APP),
            ),
            patch.object(
                impact_module,
                "preview_model_deletion",
                new=AsyncMock(return_value=impact),
            ) as preview,
        ):
            result = await impact_module.preview_dependency_impact(
                "delete_model",
                "finance",
                path="models/revenue.yaml",
            )

        preview.assert_awaited_once_with(3, "models/revenue.yaml")
        self.assertEqual(impact, result)

    async def test_update_app_preserves_omitted_fields(self):
        updated = {**APP, "description": "Updated"}

        with (
            patch.object(
                update_app_module,
                "app_context",
                new=AsyncMock(return_value=APP),
            ) as context,
            patch.object(
                update_app_module,
                "update_collection",
                new=AsyncMock(return_value=updated),
            ) as update,
        ):
            result = await update_app_module.update_app(
                "finance",
                description="Updated",
            )

        context.assert_awaited_once_with("finance", write=True)
        update.assert_awaited_once_with(
            3,
            name="Finance",
            description="Updated",
            agent_instructions="Use booked revenue",
            pipe_ids=[8, 9],
        )
        self.assertEqual("Updated", result["description"])

    async def test_delete_app_resolves_the_scoped_app(self):
        with (
            patch.object(
                delete_app_module,
                "app_context",
                new=AsyncMock(return_value=APP),
            ),
            patch.object(
                delete_app_module,
                "delete_collection",
                new=AsyncMock(return_value={"ok": True}),
            ) as delete,
        ):
            self.assertEqual(
                {"ok": True},
                await delete_app_module.delete_app("finance"),
            )

        delete.assert_awaited_once_with(3)


class MCPCalculationManagementTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_and_get_calculations_use_app_local_slugs(self):
        with (
            patch.object(
                list_calculations_module,
                "app_context",
                new=AsyncMock(return_value=APP),
            ),
            patch.object(
                list_calculations_module,
                "load_calculations",
                new=AsyncMock(return_value=[CALCULATION]),
            ) as load,
        ):
            listed = await list_calculations_module.list_calculations("finance")

        load.assert_awaited_once_with(collection_id=3)
        self.assertEqual("monthly_revenue", listed["calculations"][0]["slug"])
        self.assertNotIn("content", listed["calculations"][0])

        with patch.object(
            get_calculation_module,
            "calculation_context",
            new=AsyncMock(return_value=(APP, CALCULATION)),
        ):
            detail = await get_calculation_module.get_calculation(
                "finance",
                "monthly_revenue",
            )

        self.assertEqual(CALCULATION["content"], detail["content"])

    async def test_manage_calculation_create_update_and_delete(self):
        with (
            patch.object(
                manage_calculation_module,
                "app_context",
                new=AsyncMock(return_value=APP),
            ) as app_context,
            patch.object(
                manage_calculation_module,
                "create_calculation",
                new=AsyncMock(return_value=CALCULATION),
            ) as create,
        ):
            created = await manage_calculation_module.manage_calculation(
                "finance",
                "create",
                name="Monthly revenue",
                content=CALCULATION["content"],
            )

        app_context.assert_awaited_once_with("finance", write=True)
        create.assert_awaited_once_with(
            collection_id=3,
            name="Monthly revenue",
            content=CALCULATION["content"],
        )
        self.assertEqual("monthly_revenue", created["slug"])

        with (
            patch.object(
                manage_calculation_module,
                "calculation_context",
                new=AsyncMock(return_value=(APP, CALCULATION)),
            ),
            patch.object(
                manage_calculation_module,
                "update_calculation",
                new=AsyncMock(return_value=CALCULATION),
            ) as update,
        ):
            await manage_calculation_module.manage_calculation(
                "finance",
                "update",
                calculation="monthly_revenue",
                content=CALCULATION["content"],
                expected_content=CALCULATION["content"],
            )

        update.assert_awaited_once_with(
            7,
            content=CALCULATION["content"],
            expected_content=CALCULATION["content"],
        )

        with (
            patch.object(
                manage_calculation_module,
                "calculation_context",
                new=AsyncMock(return_value=(APP, CALCULATION)),
            ),
            patch.object(
                manage_calculation_module,
                "delete_calculation",
                new=AsyncMock(return_value={"ok": True}),
            ) as delete,
        ):
            await manage_calculation_module.manage_calculation(
                "finance",
                "delete",
                calculation="monthly_revenue",
            )

        delete.assert_awaited_once_with(7)

    async def test_calculation_operations_resolve_the_scoped_calculation(self):
        with (
            patch.object(
                validate_calculation_module,
                "calculation_context",
                new=AsyncMock(return_value=(APP, CALCULATION)),
            ),
            patch.object(
                validate_calculation_module,
                "validate_document",
                new=AsyncMock(return_value={"valid": True}),
            ) as validate,
        ):
            self.assertEqual(
                {"valid": True},
                await validate_calculation_module.validate_calculation(
                    "finance",
                    "monthly_revenue",
                ),
            )
        validate.assert_awaited_once_with(7, content=None)

        with (
            patch.object(
                execute_calculation_module,
                "calculation_context",
                new=AsyncMock(return_value=(APP, CALCULATION)),
            ),
            patch.object(
                execute_calculation_module,
                "execute_document",
                new=AsyncMock(return_value={"ok": True}),
            ) as execute,
        ):
            await execute_calculation_module.execute_calculation(
                "finance",
                "monthly_revenue",
                parameters={"region": "North"},
            )
        execute.assert_awaited_once_with(
            7,
            content=None,
            target_node_id=None,
            parameters={"region": "North"},
        )

        with (
            patch.object(
                options_module,
                "calculation_context",
                new=AsyncMock(return_value=(APP, CALCULATION)),
            ),
            patch.object(
                options_module,
                "calculation_parameter_options",
                new=AsyncMock(return_value={"options": ["North"]}),
            ) as options,
        ):
            await options_module.list_calculation_parameter_options(
                "finance",
                "monthly_revenue",
                "region",
            )
        options.assert_awaited_once_with(7, "region", content=None, search=None)


class MCPRelationshipAndModelManagementTests(unittest.IsolatedAsyncioTestCase):
    async def test_relationship_tools_delegate_to_the_shared_services(self):
        with (
            patch.object(
                list_relationships_module,
                "app_context",
                new=AsyncMock(return_value=APP),
            ),
            patch.object(
                list_relationships_module,
                "get_collection_relationships",
                new=AsyncMock(return_value={"relationships": []}),
            ) as load,
        ):
            await list_relationships_module.list_relationships("finance")
        load.assert_awaited_once_with(3)

        with (
            patch.object(
                draft_relationship_module,
                "app_context",
                new=AsyncMock(return_value=APP),
            ) as context,
            patch.object(
                draft_relationship_module,
                "relationship_draft",
                new=AsyncMock(return_value={"path": "relationships.yaml"}),
            ) as draft,
        ):
            await draft_relationship_module.draft_relationship(
                "finance",
                "orders",
                target_cube="customers",
                source_member="customer_id",
                target_member="id",
                source_primary_key="id",
                target_primary_key="id",
            )
        context.assert_awaited_once_with("finance", write=True)
        draft.assert_awaited_once_with(
            3,
            source_cube="orders",
            target_cube="customers",
            source_member="customer_id",
            target_member="id",
            relationship="many_to_one",
            source_primary_key="id",
            target_primary_key="id",
            existing_id=None,
            remove=False,
        )

        with (
            patch.object(
                validate_relationships_module,
                "app_context",
                new=AsyncMock(return_value=APP),
            ),
            patch.object(
                validate_relationships_module,
                "validate_collection_relationships",
                new=AsyncMock(return_value={"valid": True}),
            ) as validate,
        ):
            await validate_relationships_module.validate_relationships("finance")
        validate.assert_awaited_once_with(3)

    async def test_overlay_deletion_is_app_scoped_and_write_guarded(self):
        with (
            patch.object(
                delete_overlay_module,
                "app_context",
                new=AsyncMock(return_value=APP),
            ) as context,
            patch.object(
                delete_overlay_module,
                "remove_collection_overlay",
                new=AsyncMock(return_value={"ok": True}),
            ) as delete,
        ):
            result = await delete_overlay_module.delete_semantic_overlay(
                "finance",
                "relationships.yaml",
            )

        context.assert_awaited_once_with("finance", write=True)
        delete.assert_awaited_once_with(3, "relationships.yaml")
        self.assertEqual({"ok": True}, result)


if __name__ == "__main__":
    unittest.main()
