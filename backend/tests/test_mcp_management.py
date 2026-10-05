import unittest

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

from app.routers.mcp import create_artifact as create_artifact_module
from app.routers.mcp import delete_artifact as delete_artifact_module
from app.routers.mcp import delete_semantic_overlay as delete_overlay_module
from app.routers.mcp import draft_relationship as draft_relationship_module
from app.routers.mcp import get_connection_metadata as metadata_module
from app.routers.mcp import list_connections as list_connections_module
from app.routers.mcp import list_relationships as list_relationships_module
from app.routers.mcp import management as management_module
from app.routers.mcp import preview_dependency_impact as impact_module
from app.routers.mcp import update_artifact as update_artifact_module
from app.routers.mcp import validate_relationships as validate_relationships_module

ARTIFACT = {
    "id": 3,
    "name": "Finance",
    "slug": "finance",
    "description": "Finance data",
    "agent_instructions": "Use booked revenue",
    "pipe_ids": [8, 9],
    "pipe_count": 2,
    "cube_count": 4,
}


class MCPArtifactManagementTests(unittest.IsolatedAsyncioTestCase):
    async def test_shared_write_resolver_authorizes_before_loading_the_artifact(self):
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
                await management_module.artifact_context("finance", write=True)

        require_collection.assert_not_awaited()

    async def test_connection_discovery_supports_global_and_artifact_scopes(self):
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

    async def test_source_description_supports_global_and_artifact_scopes(self):
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

    async def test_create_artifact_delegates_to_the_collection_service(self):
        created = {**ARTIFACT, "pipe_ids": [8], "pipe_count": 1}

        with (
            patch.object(create_artifact_module, "require_mcp_write_access") as write,
            patch.object(
                create_artifact_module,
                "create_collection",
                new=AsyncMock(return_value=created),
            ) as create,
        ):
            result = await create_artifact_module.create_artifact(
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
                "artifact_context",
                new=AsyncMock(return_value=ARTIFACT),
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

    async def test_update_artifact_preserves_omitted_fields(self):
        updated = {**ARTIFACT, "description": "Updated"}

        with (
            patch.object(
                update_artifact_module,
                "artifact_context",
                new=AsyncMock(return_value=ARTIFACT),
            ) as context,
            patch.object(
                update_artifact_module,
                "update_collection",
                new=AsyncMock(return_value=updated),
            ) as update,
        ):
            result = await update_artifact_module.update_artifact(
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

    async def test_delete_artifact_resolves_the_scoped_artifact(self):
        with (
            patch.object(
                delete_artifact_module,
                "artifact_context",
                new=AsyncMock(return_value=ARTIFACT),
            ),
            patch.object(
                delete_artifact_module,
                "delete_collection",
                new=AsyncMock(return_value={"ok": True}),
            ) as delete,
        ):
            self.assertEqual(
                {"ok": True},
                await delete_artifact_module.delete_artifact("finance"),
            )

        delete.assert_awaited_once_with(3)


class MCPRelationshipAndModelManagementTests(unittest.IsolatedAsyncioTestCase):
    async def test_relationship_tools_delegate_to_the_shared_services(self):
        with (
            patch.object(
                list_relationships_module,
                "artifact_context",
                new=AsyncMock(return_value=ARTIFACT),
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
                "artifact_context",
                new=AsyncMock(return_value=ARTIFACT),
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
                "artifact_context",
                new=AsyncMock(return_value=ARTIFACT),
            ),
            patch.object(
                validate_relationships_module,
                "validate_collection_relationships",
                new=AsyncMock(return_value={"valid": True}),
            ) as validate,
        ):
            await validate_relationships_module.validate_relationships("finance")
        validate.assert_awaited_once_with(3)

    async def test_overlay_deletion_is_artifact_scoped_and_write_guarded(self):
        with (
            patch.object(
                delete_overlay_module,
                "artifact_context",
                new=AsyncMock(return_value=ARTIFACT),
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
