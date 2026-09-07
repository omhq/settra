import importlib
import unittest

from unittest.mock import patch

from fastapi import Request, Response

from app.common import product
from app.routers import settings


class ProductSettingsTests(unittest.IsolatedAsyncioTestCase):
    def test_ai_client_description_comes_from_its_own_environment_variable(self):
        try:
            with patch.dict(
                "os.environ",
                {
                    "PRODUCT_NAME": "Example Product",
                    "AI_CLIENT_DESCRIPTION": "Custom MCP client description.",
                },
            ):
                configured_product = importlib.reload(product)

                self.assertEqual(
                    configured_product.AI_CLIENT_DESCRIPTION,
                    "Custom MCP client description.",
                )
                self.assertNotIn(
                    configured_product.PRODUCT_NAME,
                    configured_product.AI_CLIENT_DESCRIPTION,
                )
        finally:
            importlib.reload(product)

    def test_blank_ai_client_description_remains_empty(self):
        try:
            with patch.dict(
                "os.environ",
                {
                    "PRODUCT_NAME": "Example Product",
                    "AI_CLIENT_DESCRIPTION": "   ",
                },
            ):
                configured_product = importlib.reload(product)

                self.assertEqual(configured_product.AI_CLIENT_DESCRIPTION, "")
        finally:
            importlib.reload(product)

    async def test_product_settings_exposes_managed_deployment_mode(self):
        response = Response()

        with patch.dict("os.environ", {"DEPLOYMENT_MODE": "managed"}):
            payload = await settings.product_settings(response)

        self.assertEqual(payload["deployment_mode"], "managed")
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    async def test_deployment_settings_resolves_public_url(self):
        request = Request(
            {
                "type": "http",
                "scheme": "https",
                "server": ("app.settra.io", 443),
                "path": "/api/settings",
                "headers": [(b"host", b"app.settra.io")],
            }
        )
        response = Response()
        identity = type(
            "Identity",
            (),
            {
                "email": "owner@example.com",
                "organization_id": 7,
                "organization_name": "Example",
                "organization_slug": "example",
                "role": "owner",
            },
        )()

        with (
            patch.object(settings, "current_identity", return_value=identity),
            patch.dict(
                "os.environ",
                {"DEPLOYMENT_MODE": "managed", "PUBLIC_URL": ""},
            ),
        ):
            payload = await settings.deployment_settings(request, response)

        self.assertEqual(payload["deployment_mode"], "managed")
        self.assertEqual(payload["public_url"], "https://app.settra.io")
        self.assertEqual(payload["mcp_url"], "https://app.settra.io/mcp")


if __name__ == "__main__":
    unittest.main()
