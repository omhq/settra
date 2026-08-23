import os
import unittest

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from fastapi import HTTPException

from app.routers.oauth import _validate_redirect_uri, router


class OAuthDiscoveryTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)
        self.environment = patch.dict(
            os.environ,
            {
                "SETTRA_OAUTH_ENABLED": "true",
                "SETTRA_PUBLIC_URL": "https://example.com",
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


if __name__ == "__main__":
    unittest.main()
