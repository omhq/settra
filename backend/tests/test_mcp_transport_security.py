import os
import unittest
from unittest.mock import patch

from app.routers.mcp.common import _csv_env


class MCPTransportSecurityConfigTests(unittest.TestCase):
    def test_csv_env_returns_complete_configured_allowlist(self):
        with patch.dict(
            os.environ,
            {"MCP_ALLOWED_HOSTS": "localhost, example.com:443,localhost:*"},
        ):
            self.assertEqual(
                ["localhost", "example.com:443", "localhost:*"],
                _csv_env("MCP_ALLOWED_HOSTS"),
            )

    def test_csv_env_has_no_implicit_allowlist(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual([], _csv_env("MCP_ALLOWED_HOSTS"))


if __name__ == "__main__":
    unittest.main()
