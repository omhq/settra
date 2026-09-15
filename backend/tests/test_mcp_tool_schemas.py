import json
import unittest

from unittest.mock import AsyncMock, patch

from app.routers.mcp.resources import cube_catalog_resource, cube_model_resource
from app.routers.mcp.server import mcp_server


class MCPToolSchemaTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tools = {tool.name: tool for tool in await mcp_server.list_tools()}

    def _properties(self, tool_name):
        return self.tools[tool_name].inputSchema["properties"]

    async def test_deprecated_overlay_upsert_is_removed(self):
        self.assertNotIn("save_semantic_overlay", self.tools)
        self.assertIn("create_semantic_overlay", self.tools)
        self.assertIn("update_semantic_overlay", self.tools)

    async def test_every_paginated_tool_exposes_its_cursor_inputs(self):
        connection = self._properties("get_connection_metadata")
        cubes = self._properties("list_cubes")
        cube_meta = self._properties("get_cube_meta")

        self.assertTrue(
            {
                "search",
                "include",
                "cursor",
                "limit",
                "column_cursor",
                "column_limit",
            }.issubset(connection)
        )
        self.assertTrue(
            {"search", "include", "cursor", "limit", "member_limit"}.issubset(cubes)
        )
        self.assertTrue(
            {"search", "include", "cursor", "limit", "member_limit"}.issubset(cube_meta)
        )
        self.assertIn(
            "column_page.next_column_cursor",
            connection["column_cursor"]["description"],
        )

    async def test_query_schema_accepts_one_object_and_not_an_array(self):
        query_schema = self._properties("query_cube")["query"]

        self.assertEqual("object", query_schema["type"])
        self.assertNotIn("anyOf", query_schema)

    async def test_validation_path_schema_explains_replacements(self):
        path_schema = self._properties("validate_semantic_overlay")["path"]

        self.assertIn("existing generated overlay path", path_schema["description"])

    async def test_sync_connection_is_an_explicit_write_tool(self):
        tool = self.tools["sync_connection"]

        self.assertEqual(
            {"collection", "connection_id"},
            set(self._properties(tool.name)),
        )
        self.assertFalse(tool.annotations.readOnlyHint)
        self.assertTrue(tool.annotations.destructiveHint)
        self.assertFalse(tool.annotations.idempotentHint)
        self.assertTrue(tool.annotations.openWorldHint)


class MCPResourcePaginationTests(unittest.IsolatedAsyncioTestCase):
    async def test_fixed_cube_catalog_resource_omits_unusable_cursor(self):
        with patch(
            "app.routers.mcp.resources.semantic_catalog",
            new=AsyncMock(
                return_value={
                    "cubes": [{"name": "one"}],
                    "page": {"next_cursor": 5, "total": 9},
                }
            ),
        ), patch(
            "app.routers.mcp.resources.collection_cube_names",
            new=AsyncMock(return_value={"one"}),
        ):
            result = json.loads(await cube_catalog_resource("finance"))

        self.assertEqual({"total": 9}, result["page"])

    async def test_model_resource_decodes_nested_model_path(self):
        with patch(
            "app.routers.mcp.resources.collection_cube_names",
            new=AsyncMock(return_value={"finance_bank_transactions"}),
        ), patch(
            "app.routers.mcp.resources.read_model_file",
            return_value={
                "content": "cubes: []\n",
                "cube_names": ["finance_bank_transactions"],
                "view_names": [],
            },
        ) as read_model_file:
            result = await cube_model_resource(
                "finance",
                "overlays%2Fgenerated%2Ffinance_bank_transactions.yaml",
            )

        self.assertEqual("cubes: []\n", result)
        read_model_file.assert_called_once_with(
            "overlays/generated/finance_bank_transactions.yaml"
        )

    async def test_model_resource_rejects_encoded_path_traversal(self):
        with patch(
            "app.routers.mcp.resources.collection_cube_names",
            new=AsyncMock(return_value={"finance_bank_transactions"}),
        ):
            with self.assertRaisesRegex(ValueError, "Invalid Cube model file path"):
                await cube_model_resource("finance", "..%2Fsecrets.yaml")


if __name__ == "__main__":
    unittest.main()
