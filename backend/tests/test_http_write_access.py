import unittest
import logging
from contextlib import ExitStack
from dataclasses import replace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import Identity, reset_current_identity, set_current_identity
from app.errors import ApplicationError
from app.routers import (
    calculations,
    collections,
    connections,
    google_oauth,
    health,
    organizations,
    semantics,
)
from app.routers.error_handlers import application_error_handler
from app.routers.mcp.common import require_mcp_write_access

OWNER = Identity(
    user_id=1,
    organization_id=1,
    email="owner@example.com",
    display_name="Owner",
    organization_name="Workspace",
    organization_slug="workspace",
    organization_kind="personal",
    role="owner",
)


class HTTPWriteAccessTests(unittest.TestCase):
    def setUp(self):
        httpx_logger = logging.getLogger("httpx")
        self.addCleanup(httpx_logger.setLevel, httpx_logger.level)
        httpx_logger.setLevel(logging.WARNING)
        self.app = FastAPI()
        self.app.add_exception_handler(ApplicationError, application_error_handler)
        for module in (
            calculations,
            collections,
            connections,
            google_oauth,
            health,
            organizations,
            semantics,
        ):
            self.app.include_router(module.router, prefix="/api")

    def test_every_workspace_mutation_rejects_read_only_identities_before_io(self):
        overlay = {"path": "test.yaml", "content": "cubes: []"}
        requests = (
            ("POST", "/collections", {"name": "Collection"}),
            ("PUT", "/collections/1", {"name": "Collection"}),
            ("DELETE", "/collections/1", None),
            ("POST", "/connections", {"name": "Source", "credentials": {}}),
            ("PUT", "/connections/1", {"name": "Source", "credentials": {}}),
            ("DELETE", "/connections/1", None),
            ("POST", "/connections/1/retry", None),
            ("POST", "/connections/1/sync", None),
            ("PUT", "/connections/1/sync-config", {"content": "version: 1"}),
            ("POST", "/health/data/1/refresh", None),
            ("POST", "/semantics/model/sync", None),
            ("PUT", "/semantics/model/files/test.yaml", {"content": "cubes: []"}),
            ("DELETE", "/semantics/model/files/test.yaml", None),
            ("POST", "/collections/1/relationships/draft", {"source_cube": "orders"}),
            ("POST", "/collections/1/overlays/validate", overlay),
            ("POST", "/collections/1/overlays", overlay),
            ("DELETE", "/collections/1/overlays/test.yaml", None),
            ("POST", "/google-oauth/start", None),
            ("DELETE", "/google-oauth", None),
            ("POST", "/google-picker/session", None),
            (
                "POST",
                "/calculations",
                {"collection_id": 1, "name": "Calculation", "content": "nodes: []"},
            ),
            ("PUT", "/calculations/1", {"content": "nodes: []"}),
            ("PUT", "/calculations/1/collection", {"collection_id": 1}),
            ("DELETE", "/calculations/1", None),
            ("PUT", "/organizations/1", {"name": "Workspace"}),
        )
        denied = (
            replace(OWNER, role="member"),
            replace(OWNER, role="viewer"),
            replace(OWNER, oauth_scopes=frozenset({"settra:read"})),
        )
        with ExitStack() as stack:
            io = [
                stack.enter_context(
                    patch(target, side_effect=AssertionError("Unauthorized IO"))
                )
                for target in (
                    "app.collection_service.db_connection",
                    "app.calculation_service.db_connection",
                    "app.routers.connections._connection_row",
                    "app.routers.connections.run_connection_sync",
                    "app.routers.connections.retry_connection_status",
                    "app.routers.connections.generate_connection_metadata",
                    "app.routers.health.refresh_connection_data",
                    "app.routers.semantics.sync_cube_model",
                    "app.routers.google_oauth._client_id",
                    "app.routers.google_oauth.load_google_oauth_secret",
                    "app.routers.google_oauth.delete_google_oauth_secret",
                    "app.routers.organizations.db_connection",
                    "app.routers.collections.get_collection",
                )
            ]
            with TestClient(self.app) as client:
                for identity in denied:
                    token = set_current_identity(identity)
                    try:
                        for method, path, payload in requests:
                            with self.subTest(
                                role=identity.role,
                                scopes=identity.oauth_scopes,
                                method=method,
                                path=path,
                            ):
                                response = client.request(
                                    method, f"/api{path}", json=payload
                                )
                                self.assertEqual(
                                    403, response.status_code, response.text
                                )
                    finally:
                        reset_current_identity(token)
            for mocked in io:
                mocked.assert_not_called()

    def test_owner_and_admin_can_sync(self):
        with TestClient(self.app) as client, patch(
            "app.routers.connections.run_connection_sync",
            new=AsyncMock(return_value={"ok": True}),
        ) as sync:
            for role in ("owner", "admin"):
                token = set_current_identity(replace(OWNER, role=role))
                try:
                    self.assertEqual(
                        200, client.post("/api/connections/1/sync").status_code
                    )
                finally:
                    reset_current_identity(token)
            self.assertEqual(2, sync.await_count)

    def test_read_only_post_operations_remain_available(self):
        calls = (
            (
                "/connections/1/metadata",
                None,
                "generate_connection_metadata",
                connections,
            ),
            (
                "/collections/1/query",
                {"query": {"measures": ["orders.row_count"]}},
                "execute_collection_query",
                collections,
            ),
            (
                "/collections/1/relationships/validate",
                None,
                "validate_collection_relationships",
                collections,
            ),
            (
                "/collections/1/pipes/1/tables/rows/sample",
                {},
                "sample_connection_table",
                collections,
            ),
            (
                "/collections/1/pipes/1/tables/rows/profile",
                {},
                "profile_connection_table",
                collections,
            ),
            ("/calculations/1/validate", {}, "validate_calculation", calculations),
            ("/calculations/1/execute", {}, "execute_calculation", calculations),
            (
                "/calculations/1/parameters/customer/options",
                {},
                "calculation_parameter_options",
                calculations,
            ),
        )
        with TestClient(self.app) as client, patch.object(
            collections, "get_collection", new=AsyncMock(return_value={"slug": "sales"})
        ), patch.object(collections, "require_pipe_in_collection", new=AsyncMock()):
            for role in ("member", "viewer"):
                token = set_current_identity(replace(OWNER, role=role))
                try:
                    for path, payload, function, module in calls:
                        with self.subTest(role=role, path=path), patch.object(
                            module, function, new=AsyncMock(return_value={"ok": True})
                        ) as operation:
                            self.assertEqual(
                                200,
                                client.post(f"/api{path}", json=payload).status_code,
                            )
                            operation.assert_awaited_once()
                finally:
                    reset_current_identity(token)

    def test_mcp_write_guard_maps_transport_neutral_denials(self):
        for role in ("member", "viewer"):
            token = set_current_identity(replace(OWNER, role=role))
            try:
                with self.assertRaisesRegex(ValueError, "Owner or admin"):
                    require_mcp_write_access()
            finally:
                reset_current_identity(token)
