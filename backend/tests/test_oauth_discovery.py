import os
import unittest

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.oauth import router


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


if __name__ == "__main__":
    unittest.main()
