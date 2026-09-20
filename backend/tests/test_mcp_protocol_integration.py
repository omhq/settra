import json
import tempfile
import unittest

from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.auth import Identity, reset_current_identity, set_current_identity
from app.cube.model import read_model_file, save_model_file
from app.errors import ApplicationError
from app.routers import collections
from app.routers.error_handlers import application_error_handler
from app.routers.mcp import mcp_app, mcp_server

IDENTITY = Identity(
    user_id=1,
    organization_id=1,
    email="owner@example.com",
    display_name="Owner",
    organization_name="Workspace",
    organization_slug="workspace",
    organization_kind="personal",
    role="owner",
    oauth_scopes=frozenset({"settra:read", "settra:write"}),
)

EXPECTED_TOOLS = {
    "create_app",
    "create_semantic_overlay",
    "delete_app",
    "delete_semantic_overlay",
    "draft_relationship",
    "execute_app_graph",
    "execute_calculation",
    "get_app_graph",
    "get_calculation",
    "get_collection_context",
    "get_connection_metadata",
    "get_cube",
    "get_cube_meta",
    "get_semantic_overlay",
    "list_calculation_parameter_options",
    "list_app_graph_parameter_options",
    "list_calculations",
    "list_collections",
    "list_connections",
    "list_cubes",
    "list_relationships",
    "list_semantic_overlays",
    "manage_calculation",
    "manage_app_graph",
    "preview_dependency_impact",
    "profile_connection_table",
    "query_cube",
    "sample_connection_table",
    "sync_connection",
    "update_app",
    "update_semantic_overlay",
    "validate_calculation",
    "validate_app_graph",
    "validate_relationships",
    "validate_semantic_overlay",
}

INITIAL_OVERLAY = """\
cubes:
  - name: orders_metrics
    sql_table: public.orders
    meta:
      settra:
        purpose: Test concurrent protocol writes.
        requirement: Preserve the first accepted replacement.
        grain: One row per order.
        assumptions: []
        evidence:
          - source: Protocol integration fixture.
    measures:
      - name: rows
        type: count
"""


def overlay_with_description(description: str) -> str:
    return INITIAL_OVERLAY.replace(
        "Test concurrent protocol writes.",
        description,
    )


@asynccontextmanager
async def protocol_lifespan(_app: FastAPI):
    async with mcp_server.session_manager.run():
        yield


def protocol_app() -> FastAPI:
    app = FastAPI(lifespan=protocol_lifespan)
    app.add_exception_handler(ApplicationError, application_error_handler)

    @app.middleware("http")
    async def set_test_identity(request: Request, call_next):
        token = set_current_identity(IDENTITY)
        try:
            return await call_next(request)
        finally:
            reset_current_identity(token)

    app.include_router(collections.router, prefix="/api")
    app.mount("/mcp", mcp_app)
    return app


class MCPProtocolIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        security = mcp_server.settings.transport_security
        cls.allowed_hosts = list(security.allowed_hosts)
        security.allowed_hosts = ["localhost"]
        cls.request_log = patch(
            "app.routers.mcp.common.record_mcp_request",
            new=AsyncMock(),
        )
        cls.request_log.start()
        cls.client_context = TestClient(protocol_app())
        cls.client = cls.client_context.__enter__()
        cls.request_id = 0

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)
        cls.request_log.stop()
        mcp_server.settings.transport_security.allowed_hosts = cls.allowed_hosts

    @classmethod
    def rpc(cls, method: str, params: dict, *, path: str = "/mcp/") -> dict:
        cls.request_id += 1
        response = cls.client.post(
            path,
            headers={
                "accept": "application/json, text/event-stream",
                "host": "localhost",
            },
            json={
                "jsonrpc": "2.0",
                "id": cls.request_id,
                "method": method,
                "params": params,
            },
        )
        if response.status_code != 200:
            raise AssertionError(response.text)

        payload = response.json()
        if "error" in payload:
            raise AssertionError(payload["error"])

        return payload["result"]

    @classmethod
    def call_tool(
        cls,
        name: str,
        arguments: dict,
        *,
        path: str = "/mcp/",
    ) -> dict:
        return cls.rpc(
            "tools/call",
            {"name": name, "arguments": arguments},
            path=path,
        )

    def test_protocol_negotiation_discovery_tools_resources_and_pinned_app(self):
        initialized = self.rpc(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "integration-test", "version": "1"},
            },
        )
        self.assertEqual("2025-06-18", initialized["protocolVersion"])

        tools = self.rpc("tools/list", {})
        self.assertEqual(EXPECTED_TOOLS, {tool["name"] for tool in tools["tools"]})
        templates = self.rpc("resources/templates/list", {})
        self.assertEqual(4, len(templates["resourceTemplates"]))

        collection = {
            "id": 1,
            "name": "Finance",
            "slug": "finance",
            "description": "Finance app",
            "agent_instructions": "Use approved metrics.",
            "pipe_count": 0,
            "table_count": 0,
            "cube_count": 1,
            "calculation_count": 0,
            "pipes": [],
            "tables": [],
            "cube_names": ["orders_metrics"],
        }

        with patch(
            "app.routers.mcp.list_collections.load_collections",
            new=AsyncMock(return_value=[collection]),
        ):
            listed = self.call_tool("list_collections", {})
        self.assertFalse(listed.get("isError"))
        self.assertIn("Finance", json.dumps(listed))

        with (
            patch(
                "app.routers.mcp.resources.collection_cube_names",
                new=AsyncMock(return_value={"orders_metrics"}),
            ),
            patch(
                "app.routers.mcp.resources.load_cube_meta",
                new=AsyncMock(
                    return_value={
                        "cubes": [
                            {"name": "orders_metrics"},
                            {"name": "outside_app"},
                        ]
                    }
                ),
            ),
        ):
            resource = self.rpc(
                "resources/read",
                {"uri": "settra://collections/finance/semantics/meta"},
            )
        resource_text = resource["contents"][0]["text"]
        self.assertIn("orders_metrics", resource_text)
        self.assertNotIn("outside_app", resource_text)

        require_collection = AsyncMock(return_value=collection)
        with patch(
            "app.routers.mcp.get_collection_context.require_collection",
            new=require_collection,
        ):
            pinned = self.call_tool(
                "get_collection_context",
                {"collection": "wrong_app"},
                path="/mcp/collections/finance",
            )
        self.assertFalse(pinned.get("isError"))
        require_collection.assert_awaited_once_with("finance")

    def test_http_write_wins_and_stale_mcp_replacement_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = "overlays/generated/organizations/1/collections/1/orders.yaml"
            http_content = overlay_with_description("Accepted HTTP replacement.")
            stale_mcp_content = overlay_with_description("Stale MCP replacement.")
            context = {
                "id": 1,
                "name": "Finance",
                "slug": "finance",
                "cube_names": ["orders_metrics"],
                "pipe_ids": [],
            }

            with patch("app.cube.model.CUBE_MODEL_DIR", root):
                save_model_file(path, INITIAL_OVERLAY)

                with (
                    patch(
                        "app.collection_build_service.get_collection",
                        new=AsyncMock(return_value=context),
                    ),
                    patch(
                        "app.collection_build_service.validate_overlay_for_collection",
                        new=AsyncMock(return_value={"orders_metrics"}),
                    ),
                    patch(
                        "app.routers.mcp.management.require_collection",
                        new=AsyncMock(return_value=context),
                    ),
                    patch(
                        "app.semantic.overlays.wait_for_compiled_model_names",
                        new=AsyncMock(return_value={"compiled": True}),
                    ),
                ):
                    accepted = self.client.post(
                        "/api/collections/1/overlays",
                        json={
                            "path": path,
                            "content": http_content,
                            "create": False,
                            "expected_content": INITIAL_OVERLAY,
                        },
                    )
                    self.assertEqual(200, accepted.status_code, accepted.text)

                    stale = self.call_tool(
                        "update_semantic_overlay",
                        {
                            "collection": "finance",
                            "path": path,
                            "content": stale_mcp_content,
                            "expected_content": INITIAL_OVERLAY,
                        },
                    )

                self.assertTrue(stale["isError"])
                self.assertIn("changed elsewhere", json.dumps(stale))
                self.assertEqual(http_content, read_model_file(path)["content"])


if __name__ == "__main__":
    unittest.main()
