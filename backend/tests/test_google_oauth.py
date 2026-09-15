import json
import os
import unittest
from contextlib import asynccontextmanager

from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import patch

from fastapi import HTTPException
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import google_oauth
from app.auth import Identity, reset_current_identity, set_current_identity
from app.routers.google_oauth import _frontend_return_uri
from app.schemas import GooglePickerFileInspection
from app.sync.loader import GOOGLE_FILE_SCOPE


class GoogleOAuthReturnUriTests(unittest.TestCase):
    def test_defaults_to_backend_served_data_page(self):
        with patch.dict(os.environ, {"FRONTEND_URL": ""}):
            self.assertEqual(
                "/data?google=connected", _frontend_return_uri("connected")
            )

    def test_returns_to_separate_vite_origin(self):
        with patch.dict(
            os.environ,
            {"FRONTEND_URL": "http://localhost:5173"},
        ):
            self.assertEqual(
                "http://localhost:5173/data?google=connected",
                _frontend_return_uri("connected"),
            )

    def test_rejects_frontend_urls_with_paths(self):
        with patch.dict(
            os.environ,
            {"FRONTEND_URL": "http://localhost:5173/data"},
        ):
            with self.assertRaises(HTTPException):
                _frontend_return_uri("connected")


class GoogleOAuthScopeTests(unittest.TestCase):
    def test_oauth_requests_only_file_specific_google_access(self):
        self.assertIn(GOOGLE_FILE_SCOPE, google_oauth.SCOPES)
        self.assertNotIn(
            "https://www.googleapis.com/auth/drive.readonly",
            google_oauth.SCOPES,
        )
        self.assertNotIn(
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            google_oauth.SCOPES,
        )

    def test_picker_app_id_must_be_the_numeric_project_number(self):
        with patch.dict(os.environ, {"GOOGLE_PICKER_APP_ID": "settra-dev"}):
            with self.assertRaises(HTTPException):
                google_oauth._picker_app_id()


class GooglePickerSessionTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_returns_only_a_short_lived_access_token_and_public_picker_config(
        self,
    ):
        secret = {"refresh_token": "refresh", "scopes": [GOOGLE_FILE_SCOPE]}
        credentials = SimpleNamespace(token="short-lived", expiry=None)

        with (
            patch.object(
                google_oauth,
                "load_google_oauth_secret",
                new=AsyncMock(return_value=secret),
            ),
            patch.object(
                google_oauth,
                "_run_sync",
                new=AsyncMock(return_value=credentials),
            ),
            patch.dict(
                os.environ,
                {
                    "GOOGLE_PICKER_API_KEY": "public-browser-key",
                    "GOOGLE_PICKER_APP_ID": "3539318967",
                },
            ),
        ):
            response = await google_oauth.create_google_picker_session()

        payload = json.loads(response.body)
        self.assertEqual("short-lived", payload["access_token"])
        self.assertEqual("public-browser-key", payload["api_key"])
        self.assertEqual("3539318967", payload["app_id"])
        self.assertNotIn("refresh_token", payload)
        self.assertEqual("no-store", response.headers["cache-control"])

    async def test_old_broad_scope_requires_reconnect(self):
        secret = {
            "refresh_token": "refresh",
            "scopes": ["https://www.googleapis.com/auth/drive.readonly"],
        }

        with patch.object(
            google_oauth,
            "load_google_oauth_secret",
            new=AsyncMock(return_value=secret),
        ):
            with self.assertRaises(HTTPException) as context:
                await google_oauth.create_google_picker_session()

        self.assertEqual(409, context.exception.status_code)

    async def test_inspects_picker_file_worksheets_with_saved_oauth(self):
        secret = {"refresh_token": "refresh", "scopes": [GOOGLE_FILE_SCOPE]}
        credentials = SimpleNamespace(token="short-lived")
        discovery = {
            "file_name": "Sales.xlsx",
            "mime_type": (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
            "format": "excel",
            "worksheets": ["Orders", "North, East"],
        }

        with (
            patch.object(
                google_oauth,
                "load_google_oauth_secret",
                new=AsyncMock(return_value=secret),
            ),
            patch.object(
                google_oauth,
                "_refresh_google_credentials",
                return_value=credentials,
            ),
            patch.object(
                google_oauth,
                "discover_google_drive_worksheets",
                return_value=discovery,
            ) as discover,
        ):
            result = await google_oauth.inspect_google_picker_file(
                GooglePickerFileInspection(file_id="excel-123")
            )

        self.assertEqual(discovery, result)
        discover.assert_called_once_with("excel-123", credentials)


class GoogleOAuthMembershipTests(unittest.IsolatedAsyncioTestCase):
    async def test_callback_rechecks_write_membership_before_token_exchange(self):
        database = SimpleNamespace(fetchval=AsyncMock(return_value=None))

        @asynccontextmanager
        async def connection():
            yield database

        app = FastAPI()
        app.include_router(google_oauth.router, prefix="/api")
        with (
            patch.object(google_oauth, "_verify_state", return_value=(1, 2)),
            patch.object(google_oauth, "db_connection", connection),
            patch.object(google_oauth.httpx, "AsyncClient") as exchange,
            patch.object(
                google_oauth, "save_google_oauth_secret", new_callable=AsyncMock
            ) as save,
            TestClient(app) as client,
        ):
            client.cookies.set(google_oauth.STATE_COOKIE, "signed-state")
            response = client.get(
                "/api/google-oauth/callback?state=signed-state&code=code"
            )
        self.assertEqual(403, response.status_code)
        sql, user_id, organization_id = database.fetchval.call_args.args
        self.assertIn("m.role IN ('owner', 'admin')", sql)
        self.assertIn("u.is_active = true", sql)
        self.assertEqual((1, 2), (user_id, organization_id))
        exchange.assert_not_called()
        save.assert_not_awaited()

    async def test_active_write_membership_is_allowed(self):
        database = SimpleNamespace(fetchval=AsyncMock(return_value=1))

        @asynccontextmanager
        async def connection():
            yield database

        with patch.object(google_oauth, "db_connection", connection):
            await google_oauth._require_write_membership(1, 2)
        database.fetchval.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
