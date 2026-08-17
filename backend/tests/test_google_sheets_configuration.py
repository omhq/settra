import tempfile
import unittest

from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import connection_config, connections


class GoogleSheetsConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_dir = Path(self.temp_dir.name)
        (self.config_dir / "connection.yaml").write_text(
            "name: Google Sheets\n"
            "plugin: googlesheets\n"
            "description: Sheet data for agents\n"
            "fields: []\n",
            encoding="utf-8",
        )
        (self.config_dir / "README.md").write_text(
            "# Connect Google Sheets\n\nShare the spreadsheet.\n",
            encoding="utf-8",
        )

        app = FastAPI()
        app.include_router(connections.router, prefix="/api")
        self.client = TestClient(app)
        self.config_dir_patch = patch.object(
            connection_config,
            "GOOGLE_SHEETS_CONFIG_DIR",
            self.config_dir,
        )
        self.config_dir_patch.start()

    def tearDown(self):
        self.config_dir_patch.stop()
        self.temp_dir.cleanup()

    def test_config_endpoint_returns_only_google_sheets(self):
        response = self.client.get("/api/google-sheets/config")

        self.assertEqual(response.status_code, 200)
        self.assertEqual("Google Sheets", response.json()["name"])
        self.assertNotIn("plugin", response.json())
        self.assertTrue(response.json()["has_documentation"])

    def test_documentation_endpoint_returns_markdown(self):
        response = self.client.get("/api/google-sheets/documentation")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "Google Sheets")
        self.assertEqual(
            response.json()["content"],
            "# Connect Google Sheets\n\nShare the spreadsheet.\n",
        )

    def test_documentation_endpoint_rejects_missing_guide(self):
        (self.config_dir / "README.md").unlink()

        response = self.client.get("/api/google-sheets/documentation")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Setup guide not found")


if __name__ == "__main__":
    unittest.main()
