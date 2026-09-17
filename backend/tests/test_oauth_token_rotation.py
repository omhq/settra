import asyncio
import hashlib
import json
import os
import re
import time
import unittest

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.auth import Identity
from app.routers import oauth

OWNER = Identity(
    user_id=7,
    organization_id=11,
    email="owner@example.com",
    display_name="Owner",
    organization_name="Finance",
    organization_slug="finance",
    organization_kind="team",
    role="owner",
)


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, _exc_type, _exc, _traceback):
        return False


class OAuthDatabase:
    def __init__(self):
        self.clients: dict[str, dict] = {}
        self.authorization_codes: dict[str, dict] = {}
        self.refresh_tokens: dict[str, dict] = {}
        self.membership_active = True

    def transaction(self) -> FakeTransaction:
        return FakeTransaction()

    async def fetchrow(self, query: str, *args):
        if "FROM oauth_clients" in query:
            return self.clients.get(str(args[0]))
        if "FROM oauth_authorization_codes" in query:
            return self.authorization_codes.get(str(args[0]))
        if "FROM oauth_refresh_tokens" in query:
            return self.refresh_tokens.get(str(args[0]))
        if "FROM users u" in query and "JOIN organizations" in query:
            if not self.membership_active:
                return None
            return {
                "email": OWNER.email,
                "display_name": OWNER.display_name,
                "organization_name": OWNER.organization_name,
                "organization_slug": OWNER.organization_slug,
                "organization_kind": OWNER.organization_kind,
                "role": OWNER.role,
            }

        raise AssertionError(f"Unexpected fetchrow query: {query}")

    async def fetchval(self, query: str, *_args):
        if "organization_memberships" in query:
            return 1 if self.membership_active else None

        raise AssertionError(f"Unexpected fetchval query: {query}")

    async def execute(self, query: str, *args):
        if "INSERT INTO oauth_clients" in query:
            self.clients[str(args[0])] = {
                "client_id": args[0],
                "client_name": args[1],
                "redirect_uris": args[2],
                "grant_types": args[3],
                "response_types": args[4],
                "scope": args[5],
                "token_endpoint_auth_method": args[6],
            }
            return "INSERT 0 1"

        if "INSERT INTO oauth_authorization_codes" in query:
            self.authorization_codes[str(args[0])] = {
                "code_hash": args[0],
                "client_id": args[1],
                "redirect_uri": args[2],
                "scope": args[3],
                "resource": args[4],
                "code_challenge": args[5],
                "code_challenge_method": args[6],
                "expires_at": args[7],
                "user_id": args[8],
                "organization_id": args[9],
                "consumed_at": None,
            }
            return "INSERT 0 1"

        if "UPDATE oauth_authorization_codes" in query:
            self.authorization_codes[str(args[0])]["consumed_at"] = True
            return "UPDATE 1"

        if "INSERT INTO oauth_refresh_tokens" in query:
            self.refresh_tokens[str(args[0])] = {
                "token_hash": args[0],
                "family_id": args[1],
                "client_id": args[2],
                "scope": args[3],
                "resource": args[4],
                "expires_at": args[5],
                "user_id": args[6],
                "organization_id": args[7],
                "consumed_at": None,
                "revoked_at": None,
            }
            return "INSERT 0 1"

        if "SET consumed_at = now()" in query:
            self.refresh_tokens[str(args[0])]["consumed_at"] = True
            return "UPDATE 1"

        if "SET revoked_at = COALESCE" in query:
            family_id = str(args[0])
            for token in self.refresh_tokens.values():
                if token["family_id"] == family_id:
                    token["revoked_at"] = True
            return "UPDATE"

        if "DELETE FROM oauth_refresh_tokens" in query:
            return "DELETE 0"

        raise AssertionError(f"Unexpected execute query: {query}")


class OAuthTokenRotationIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.database = OAuthDatabase()

        @asynccontextmanager
        async def database_connection():
            yield self.database

        self.database_patch = patch.object(
            oauth,
            "db_connection",
            database_connection,
        )
        self.environment = patch.dict(
            os.environ,
            {
                "MCP_OAUTH_ENABLED": "true",
                "PUBLIC_URL": "http://testserver",
                "SETTRA_OAUTH_RESOURCE": "http://testserver/mcp",
                "SETTRA_OAUTH_SCOPES": "settra:read settra:write",
                "SECRET_KEY": "oauth-integration-secret",
            },
        )
        self.database_patch.start()
        self.environment.start()

        app = FastAPI()
        app.include_router(oauth.router)
        self.client_context = TestClient(app)
        self.client = self.client_context.__enter__()

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        self.environment.stop()
        self.database_patch.stop()

    def test_consent_pkce_rotation_replay_revocation_and_membership_revocation(self):
        redirect_uri = "http://127.0.0.1:55124/callback"
        resource = "http://testserver/mcp"
        verifier = "correct-horse-battery-staple-oauth-verifier"
        challenge = oauth._base64url_encode(
            hashlib.sha256(verifier.encode("ascii")).digest()
        )

        registration = self.client.post(
            "/oauth/register",
            json={
                "client_name": "Protocol integration client",
                "redirect_uris": [redirect_uri],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "scope": "settra:read settra:write",
                "token_endpoint_auth_method": "none",
            },
        )
        self.assertEqual(201, registration.status_code, registration.text)
        client_id = registration.json()["client_id"]
        authorization = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "client-state",
            "scope": "settra:read settra:write",
            "resource": resource,
        }

        with (
            patch.object(
                oauth,
                "authenticate_user",
                new=AsyncMock(return_value=SimpleNamespace(user_id=OWNER.user_id)),
            ),
            patch.object(
                oauth,
                "organization_identities_for_user",
                new=AsyncMock(return_value=[OWNER]),
            ),
        ):
            sign_in = self.client.post(
                "/oauth/authorize",
                data={
                    **authorization,
                    "username": OWNER.email,
                    "password": "test-password",
                },
                follow_redirects=False,
            )
        self.assertEqual(200, sign_in.status_code, sign_in.text)
        ticket_match = re.search(
            r'name="identity_ticket" value="([^"]+)"',
            sign_in.text,
        )
        self.assertIsNotNone(ticket_match)
        identity_ticket = ticket_match.group(1)

        with patch.object(
            oauth,
            "identity_for_user_organization",
            new=AsyncMock(return_value=OWNER),
        ):
            consent = self.client.post(
                "/oauth/authorize",
                data={
                    **authorization,
                    "identity_ticket": identity_ticket,
                    "organization_id": str(OWNER.organization_id),
                },
                follow_redirects=False,
            )
        self.assertEqual(303, consent.status_code, consent.text)
        redirected = urlparse(consent.headers["location"])
        redirected_query = parse_qs(redirected.query)
        self.assertEqual(["client-state"], redirected_query["state"])
        code = redirected_query["code"][0]

        refresh_tokens = iter(
            (
                "refresh-one",
                "refresh-two",
                "unused-replay-replacement",
                "unused-revoked-replacement",
                "unused-membership-replacement",
            )
        )
        with patch.object(oauth, "_new_refresh_token", side_effect=refresh_tokens):
            exchange = self.client.post(
                "/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": client_id,
                    "redirect_uri": redirect_uri,
                    "code_verifier": verifier,
                    "resource": resource,
                },
            )
            self.assertEqual(200, exchange.status_code, exchange.text)
            self.assertEqual("no-store", exchange.headers["cache-control"])
            first_tokens = exchange.json()
            self.assertEqual("refresh-one", first_tokens["refresh_token"])

            request = Request(
                {
                    "type": "http",
                    "scheme": "http",
                    "server": ("testserver", 80),
                    "method": "POST",
                    "path": "/mcp/",
                    "headers": [(b"host", b"testserver")],
                }
            )
            first_claims = oauth._verify_access_token(
                first_tokens["access_token"], request
            )
            self.assertEqual(str(OWNER.user_id), first_claims["sub"])
            self.assertEqual(str(OWNER.organization_id), first_claims["org"])
            self.assertEqual("settra:read settra:write", first_claims["scope"])

            authorized_request = Request(
                {
                    "type": "http",
                    "scheme": "http",
                    "server": ("testserver", 80),
                    "method": "POST",
                    "path": "/mcp/",
                    "headers": [
                        (b"host", b"testserver"),
                        (
                            b"authorization",
                            f"Bearer {first_tokens['access_token']}".encode(),
                        ),
                    ],
                }
            )
            self.assertIsNone(
                asyncio.run(oauth.authorize_mcp_request(authorized_request))
            )
            self.assertEqual(
                OWNER.organization_id,
                authorized_request.state.identity.organization_id,
            )

            rotation = self.client.post(
                "/oauth/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": "refresh-one",
                    "client_id": client_id,
                    "resource": resource,
                    "scope": "settra:read",
                },
            )
            self.assertEqual(200, rotation.status_code, rotation.text)
            rotated_tokens = rotation.json()
            self.assertEqual("refresh-two", rotated_tokens["refresh_token"])
            rotated_claims = oauth._verify_access_token(
                rotated_tokens["access_token"], request
            )
            self.assertEqual("settra:read", rotated_claims["scope"])

            replay = self.client.post(
                "/oauth/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": "refresh-one",
                    "client_id": client_id,
                },
            )
            self.assertEqual(400, replay.status_code)
            self.assertEqual("invalid_grant", replay.json()["error"])
            self.assertIn("reuse detected", replay.json()["error_description"])

            revoked_family = self.client.post(
                "/oauth/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": "refresh-two",
                    "client_id": client_id,
                },
            )
            self.assertEqual(400, revoked_family.status_code)
            self.assertEqual("invalid_grant", revoked_family.json()["error"])

            membership_token = "membership-revoked-token"
            self.database.refresh_tokens[oauth._hash_secret(membership_token)] = {
                "token_hash": oauth._hash_secret(membership_token),
                "family_id": "membership-family",
                "client_id": client_id,
                "scope": "settra:read",
                "resource": resource,
                "expires_at": int(time.time()) + 3600,
                "user_id": OWNER.user_id,
                "organization_id": OWNER.organization_id,
                "consumed_at": None,
                "revoked_at": None,
            }
            self.database.membership_active = False
            revoked_membership = self.client.post(
                "/oauth/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": membership_token,
                    "client_id": client_id,
                },
            )
            self.assertEqual(400, revoked_membership.status_code)
            self.assertEqual("invalid_grant", revoked_membership.json()["error"])
            self.assertIn(
                "Account access was revoked",
                revoked_membership.json()["error_description"],
            )

        families: dict[str, list[dict]] = {}
        for token in self.database.refresh_tokens.values():
            families.setdefault(str(token["family_id"]), []).append(token)
        rotated_family = next(
            tokens
            for tokens in families.values()
            if any(
                token["token_hash"] == oauth._hash_secret("refresh-one")
                for token in tokens
            )
        )
        self.assertTrue(all(token["revoked_at"] for token in rotated_family))
        self.assertNotIn("refresh-one", json.dumps(self.database.refresh_tokens))


if __name__ == "__main__":
    unittest.main()
