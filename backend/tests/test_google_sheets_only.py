import importlib
import tempfile
import unittest

from pathlib import Path
from unittest.mock import patch

import aiosqlite
from pydantic import ValidationError

from app.cube import model as cube_model
from app.routers import connections
from app.schemas import ConnectionCreate

mcp_connections = importlib.import_module("app.routers.mcp.list_connections")


class GoogleSheetsRequestTests(unittest.TestCase):
    def test_create_request_has_no_plugin_choice(self):
        with self.assertRaises(ValidationError):
            ConnectionCreate.model_validate(
                {
                    "name": "Sales forecast",
                    "plugin": "anything-else",
                    "credentials": {},
                }
            )


class GoogleSheetsDatabaseFilteringTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "app.db"

        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(
                """
                CREATE TABLE connections (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    slug TEXT NOT NULL,
                    plugin TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                INSERT INTO connections VALUES
                    (1, 'Forecast', 'forecast', 'googlesheets', 'active', '2026-01-01'),
                    (2, 'Legacy source', 'legacy', 'unsupported', 'active', '2026-01-02');
                """
            )
            await db.commit()

    async def asyncTearDown(self):
        self.temp_dir.cleanup()

    async def test_http_mcp_and_model_generation_ignore_legacy_sources(self):
        with (
            patch.object(connections, "DB_PATH", self.db_path),
            patch.object(mcp_connections, "DB_PATH", self.db_path),
            patch.object(cube_model, "DB_PATH", self.db_path),
        ):
            http_rows = await connections.list_connections()
            mcp_rows = await mcp_connections.list_connections()
            model_rows = await cube_model._saved_connections()

        for rows in (http_rows, mcp_rows, model_rows):
            self.assertEqual(["googlesheets"], [row["plugin"] for row in rows])


if __name__ == "__main__":
    unittest.main()
