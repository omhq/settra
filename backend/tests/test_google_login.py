import os
import time
import unittest

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit

from fastapi import HTTPException

from app.auth import CreatedAccount, Identity, google_login_enabled
from app.routers import google_login

IDENTITY = Identity(
    user_id=7,
    organization_id=11,
    email="person@example.com",
    display_name="Person",
    organization_name="Person's workspace",
    organization_slug="bright-calm-otter-234567",
    organization_kind="personal",
    role="owner",
)


def _request(*, cookie: str = "", code_verifier: str = "") -> SimpleNamespace:
    cookies = {}
    if cookie:
        cookies[google_login.STATE_COOKIE] = cookie
    if code_verifier:
        cookies[google_login.CODE_VERIFIER_COOKIE] = code_verifier
    return SimpleNamespace(
        base_url="http://localhost:8000/",
        cookies=cookies,
    )


class GoogleLoginConfigurationTests(unittest.TestCase):
    def test_login_requests_identity_scopes_without_drive_access(self):
        self.assertEqual(("openid", "email", "profile"), google_login.SCOPES)

    def test_state_is_signed_and_expires(self):
        timestamp = str(int(time.time()))
        nonce = "login-nonce"
        state = f"{timestamp}.{nonce}.{google_login._state_signature(timestamp, nonce)}"
        self.assertEqual(nonce, google_login._verify_state(state))

        with self.assertRaises(HTTPException):
            google_login._verify_state(f"{timestamp}.{nonce}.invalid")

    def test_login_redirect_uri_is_separate_from_drive_oauth(self):
        with patch.dict(
            os.environ,
            {
                "PUBLIC_URL": "https://settra.example.com",
                "GOOGLE_LOGIN_REDIRECT_URI": "",
            },
        ):
            self.assertEqual(
                "https://settra.example.com/api/auth/google/callback",
                google_login._redirect_uri(_request()),
            )

    def test_login_requires_explicit_opt_in_and_oauth_credentials(self):
        with patch.dict(
            os.environ,
            {
                "GOOGLE_LOGIN_ENABLED": "false",
                "GOOGLE_OAUTH_CLIENT_ID": "client-id",
                "GOOGLE_OAUTH_CLIENT_SECRET": "client-secret",
            },
        ):
            self.assertFalse(google_login_enabled())

        with patch.dict(
            os.environ,
            {
                "GOOGLE_LOGIN_ENABLED": "true",
                "GOOGLE_OAUTH_CLIENT_ID": "client-id",
                "GOOGLE_OAUTH_CLIENT_SECRET": "client-secret",
            },
        ):
            self.assertTrue(google_login_enabled())


class GoogleLoginRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_sets_state_cookie_and_redirects_to_google(self):
        with (
            patch.object(google_login, "google_login_enabled", return_value=True),
            patch.dict(
                os.environ,
                {
                    "GOOGLE_OAUTH_CLIENT_ID": "client-id",
                    "GOOGLE_OAUTH_CLIENT_SECRET": "client-secret",
                    "PUBLIC_URL": "http://localhost:8000",
                },
            ),
        ):
            response = await google_login.start_google_login(_request())

        query = parse_qs(urlsplit(response.headers["location"]).query)
        self.assertEqual(["openid email profile"], query["scope"])
        self.assertEqual(
            query["nonce"][0], google_login._verify_state(query["state"][0])
        )
        self.assertEqual(["S256"], query["code_challenge_method"])
        self.assertIn(google_login.STATE_COOKIE, response.headers["set-cookie"])
        self.assertNotIn("drive", query["scope"][0])

    async def test_callback_creates_settra_session_from_verified_claims(self):
        timestamp = str(int(time.time()))
        nonce = "login-nonce"
        state = f"{timestamp}.{nonce}.{google_login._state_signature(timestamp, nonce)}"
        account = CreatedAccount(identity=IDENTITY, claimed_legacy_data=False)
        expires_at = datetime.now(timezone.utc)

        with (
            patch.object(
                google_login,
                "_exchange_and_verify_code",
                new=AsyncMock(
                    return_value={
                        "sub": "google-subject",
                        "email": "person@example.com",
                        "email_verified": True,
                        "name": "Person",
                        "nonce": nonce,
                    }
                ),
            ),
            patch.object(
                google_login,
                "authenticate_or_create_google_account",
                new=AsyncMock(return_value=account),
            ) as authenticate,
            patch.object(
                google_login,
                "create_session",
                new=AsyncMock(return_value=("session-token", "csrf-token", expires_at)),
            ),
            patch.object(google_login, "registration_enabled", return_value=True),
            patch.object(google_login, "google_login_enabled", return_value=True),
            patch.dict(os.environ, {"FRONTEND_URL": ""}),
        ):
            response = await google_login.google_login_callback(
                _request(cookie=state, code_verifier="pkce-verifier"),
                code="authorization-code",
                state=state,
            )

        self.assertEqual("/data?google=connected", response.headers["location"])
        cookies = response.headers.getlist("set-cookie")
        self.assertTrue(any("settra_session=session-token" in item for item in cookies))
        self.assertTrue(any("settra_csrf=csrf-token" in item for item in cookies))
        authenticate.assert_awaited_once_with(
            subject="google-subject",
            email="person@example.com",
            display_name="Person",
            allow_registration=True,
        )

    async def test_unverified_google_email_is_rejected(self):
        timestamp = str(int(time.time()))
        nonce = "login-nonce"
        state = f"{timestamp}.{nonce}.{google_login._state_signature(timestamp, nonce)}"

        with (
            patch.object(
                google_login,
                "_exchange_and_verify_code",
                new=AsyncMock(
                    return_value={
                        "sub": "google-subject",
                        "email": "person@example.com",
                        "email_verified": False,
                        "nonce": nonce,
                    }
                ),
            ),
            patch.object(google_login, "google_login_enabled", return_value=True),
            patch.dict(os.environ, {"FRONTEND_URL": ""}),
        ):
            response = await google_login.google_login_callback(
                _request(cookie=state, code_verifier="pkce-verifier"),
                code="authorization-code",
                state=state,
            )

        self.assertEqual("/login?google=error", response.headers["location"])


class GoogleAccountLinkingTests(unittest.IsolatedAsyncioTestCase):
    async def test_verified_email_links_an_existing_local_account(self):
        db = AsyncMock()
        db.fetchrow.side_effect = (
            None,
            {"user_id": 7, "is_active": True, "google_subject": None},
            {
                "user_id": 7,
                "email": "person@example.com",
                "display_name": "Person",
                "organization_id": 11,
                "organization_name": "Person's workspace",
                "organization_slug": "bright-calm-otter-234567",
                "organization_kind": "personal",
                "role": "owner",
            },
        )

        class Transaction:
            async def __aenter__(self):
                return None

            async def __aexit__(self, exc_type, exc, traceback):
                return False

        db.transaction = lambda: Transaction()

        @asynccontextmanager
        async def connection():
            yield db

        with patch("app.auth.db_connection", connection):
            from app.auth import authenticate_or_create_google_account

            account = await authenticate_or_create_google_account(
                subject="google-subject",
                email="Person@Example.com",
                display_name="Person",
                allow_registration=False,
            )

        self.assertEqual(IDENTITY, account.identity)
        statements = [call.args[0] for call in db.execute.await_args_list]
        self.assertTrue(
            any("INSERT INTO google_login_identities" in sql for sql in statements)
        )


if __name__ == "__main__":
    unittest.main()
