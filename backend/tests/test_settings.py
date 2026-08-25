import unittest

from unittest.mock import patch

from fastapi import Request, Response

from app.routers import settings


class ProductSettingsTests(unittest.IsolatedAsyncioTestCase):
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
