import json
import os
import unittest

from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import patch

from fastapi import HTTPException

from app.routers import google_oauth
from app.routers.google_oauth import _frontend_return_uri
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


if __name__ == "__main__":
    unittest.main()
