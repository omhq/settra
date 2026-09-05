import importlib
import unittest

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError

from app.cube import model as cube_model
from app.routers import connections
from app.schemas import ConnectionCreate

mcp_connections = importlib.import_module("app.routers.mcp.list_connections")


class GoogleDriveRequestTests(unittest.TestCase):
    def test_create_request_has_no_plugin_choice(self):
        with self.assertRaises(ValidationError):
            ConnectionCreate.model_validate(
                {
                    "name": "Sales forecast",
                    "plugin": "anything-else",
                    "credentials": {},
                }
            )

    def test_create_request_preserves_exact_worksheet_names(self):
        request = ConnectionCreate.model_validate(
            {
                "name": "Sales forecast",
                "credentials": {
                    "file_id": "sheet-123",
                    "sheets": ["Orders", "North, East"],
                },
            }
        )

        self.assertEqual(
            ["Orders", "North, East"],
            request.credentials["sheets"],
        )

    def test_create_request_preserves_composite_row_keys(self):
        request = ConnectionCreate.model_validate(
            {
                "name": "Sales forecast",
                "credentials": {"file_id": "sheet-123", "sheets": ["Orders"]},
                "row_keys": {"Orders": ["Account ID", "Order ID"]},
            }
        )

        self.assertEqual(
            {"Orders": ["Account ID", "Order ID"]},
            request.row_keys,
        )

    def test_create_request_accepts_formatted_row_key(self):
        request = ConnectionCreate.model_validate(
            {
                "name": "Sales forecast",
                "credentials": {"file_id": "sheet-123", "sheets": ["Orders"]},
                "row_keys": {
                    "Orders": {
                        "columns": ["Account ID", "Order ID"],
                        "format": "ORD-{Account ID}-{Order ID}",
                    }
                },
            }
        )

        self.assertEqual(
            {
                "columns": ["Account ID", "Order ID"],
                "format": "ORD-{Account ID}-{Order ID}",
            },
            request.row_keys["Orders"].model_dump(exclude_none=True),
        )


class GoogleDriveDatabaseFilteringTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_mcp_and_model_generation_ignore_legacy_sources(self):
        google_row = {
            "id": 1,
            "name": "Forecast",
            "slug": "forecast",
            "plugin": "googledrive",
            "status": "active",
            "created_at": "2026-01-01",
        }

        class GoogleDriveDatabase:
            async def fetch(self, query, *params):
                if "plugin = $1" not in query or params[0] != "googledrive":
                    raise AssertionError("Query did not enforce Google Drive filtering")
                return [google_row]

        @asynccontextmanager
        async def google_database():
            yield GoogleDriveDatabase()

        with (
            patch.object(connections, "db_connection", google_database),
            patch.object(
                connections,
                "current_identity",
                return_value=type("Identity", (), {"organization_id": 9})(),
            ),
            patch.object(mcp_connections, "db_connection", google_database),
            patch.object(
                mcp_connections,
                "current_organization_id",
                return_value=9,
            ),
            patch.object(cube_model, "db_connection", google_database),
            patch.object(
                mcp_connections,
                "require_collection",
                AsyncMock(return_value={"pipe_ids": [1]}),
            ),
        ):
            http_rows = await connections.list_connections()
            mcp_rows = await mcp_connections.list_connections("forecasting")
            model_rows = await cube_model._saved_connections()

        for rows in (http_rows, mcp_rows, model_rows):
            self.assertEqual(["googledrive"], [row["plugin"] for row in rows])


if __name__ == "__main__":
    unittest.main()
