import tempfile
import unittest

from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import connection_config, connections


class GoogleDriveConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_dir = Path(self.temp_dir.name)
        (self.config_dir / "connection.yaml").write_text(
            "name: Google Drive files\n"
            "plugin: googledrive\n"
            "description: Tabular Drive data for agents\n"
            "fields: []\n",
            encoding="utf-8",
        )
        (self.config_dir / "README.md").write_text(
            "# Connect Google Drive files\n\nShare the file.\n",
            encoding="utf-8",
        )

        app = FastAPI()
        app.include_router(connections.router, prefix="/api")
        self.client = TestClient(app)
        self.config_dir_patch = patch.object(
            connection_config,
            "GOOGLE_DRIVE_CONFIG_DIR",
            self.config_dir,
        )
        self.config_dir_patch.start()

    def tearDown(self):
        self.config_dir_patch.stop()
        self.temp_dir.cleanup()

    def test_config_endpoint_returns_google_drive_source(self):
        response = self.client.get("/api/google-drive/config")

        self.assertEqual(response.status_code, 200)
        self.assertEqual("Google Drive files", response.json()["name"])
        self.assertNotIn("plugin", response.json())
        self.assertTrue(response.json()["has_documentation"])

    def test_managed_config_hides_self_hosting_documentation(self):
        with patch.dict("os.environ", {"DEPLOYMENT_MODE": "managed"}):
            response = self.client.get("/api/google-drive/config")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["has_documentation"])

    def test_managed_deployment_does_not_serve_setup_guide(self):
        with patch.dict("os.environ", {"DEPLOYMENT_MODE": "managed"}):
            response = self.client.get("/api/google-drive/documentation")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Setup guide not available")

    def test_documentation_endpoint_returns_markdown(self):
        response = self.client.get("/api/google-drive/documentation")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "Google Drive files")
        self.assertEqual(
            response.json()["content"],
            "# Connect Google Drive files\n\nShare the file.\n",
        )

    def test_documentation_endpoint_rejects_missing_guide(self):
        (self.config_dir / "README.md").unlink()

        response = self.client.get("/api/google-drive/documentation")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Setup guide not found")


if __name__ == "__main__":
    unittest.main()
