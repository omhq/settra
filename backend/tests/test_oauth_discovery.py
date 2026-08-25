import os
import unittest

from dataclasses import replace
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.auth import Identity
from app.routers.oauth import (
    _granted_scope,
    _new_identity_ticket,
    _validate_redirect_uri,
    _verify_identity_ticket,
    mcp_auth_challenge,
    router,
)


class OAuthDiscoveryTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)
        self.environment = patch.dict(
            os.environ,
            {
                "MCP_OAUTH_ENABLED": "true",
                "PUBLIC_URL": "https://example.com",
                "SETTRA_OAUTH_SCOPES": "example:read example:write",
            },
        )
        self.environment.start()

    def tearDown(self):
        self.environment.stop()

    def test_openid_configuration_exposes_oauth_metadata_as_json(self):
        response = self.client.get("/.well-known/openid-configuration")

        self.assertEqual(200, response.status_code)
        self.assertEqual("application/json", response.headers["content-type"])
        self.assertEqual(
            {
                "issuer": "https://example.com",
                "authorization_endpoint": "https://example.com/oauth/authorize",
                "token_endpoint": "https://example.com/oauth/token",
                "registration_endpoint": "https://example.com/oauth/register",
                "response_types_supported": ["code"],
                "grant_types_supported": [
                    "authorization_code",
                    "refresh_token",
                ],
                "token_endpoint_auth_methods_supported": ["none"],
                "code_challenge_methods_supported": ["S256"],
                "scopes_supported": ["example:read", "example:write"],
                "resource_parameter_supported": True,
            },
            response.json(),
        )

    def test_openid_and_oauth_discovery_documents_match(self):
        openid_response = self.client.get("/.well-known/openid-configuration")
        oauth_response = self.client.get("/.well-known/oauth-authorization-server")

        self.assertEqual(oauth_response.json(), openid_response.json())

    def test_mcp_challenge_requires_read_scope_only(self):
        response = mcp_auth_challenge(self.client.build_request("GET", "/mcp/"))

        self.assertIn('scope="settra:read"', response.headers["WWW-Authenticate"])
        self.assertNotIn("settra:write", response.headers["WWW-Authenticate"])

    def test_native_app_loopback_redirect_is_allowed(self):
        _validate_redirect_uri("http://127.0.0.1:55124/callback/codex")
        _validate_redirect_uri("http://[::1]:55124/callback/codex")

    def test_non_loopback_http_redirect_is_rejected(self):
        with self.assertRaises(HTTPException) as context:
            _validate_redirect_uri("http://example.com/callback")

        self.assertEqual(400, context.exception.status_code)

    def test_lookalike_loopback_redirect_is_rejected(self):
        with self.assertRaises(HTTPException) as context:
            _validate_redirect_uri("http://127.0.0.1.example.com/callback")

        self.assertEqual(400, context.exception.status_code)

    def test_identity_ticket_is_bound_to_authorization_params(self):
        params = {
            "response_type": "code",
            "client_id": "client",
            "redirect_uri": "https://chatgpt.com/callback",
            "code_challenge": "challenge",
            "code_challenge_method": "S256",
            "state": "state",
            "scope": "settra:read settra:write",
            "resource": "https://example.com",
        }
        ticket = _new_identity_ticket(42, params)

        self.assertEqual(42, _verify_identity_ticket(ticket, params))
        with self.assertRaises(ValueError):
            _verify_identity_ticket(ticket, {**params, "client_id": "other"})

    def test_write_scope_is_removed_for_non_admin_members(self):
        identity = Identity(
            user_id=1,
            organization_id=2,
            email="member@example.com",
            display_name="Member",
            organization_name="Workspace",
            organization_slug="workspace",
            organization_kind="team",
            role="member",
        )

        self.assertEqual(
            "settra:read",
            _granted_scope("settra:read settra:write", identity),
        )
        self.assertEqual(
            "settra:read settra:write",
            _granted_scope(
                "settra:read settra:write",
                replace(identity, role="admin"),
            ),
        )


if __name__ == "__main__":
    unittest.main()
