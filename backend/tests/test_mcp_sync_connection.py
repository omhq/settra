import unittest

from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.routers.mcp.sync_connection import sync_connection


class SyncConnectionToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_requires_write_access_before_loading_collection_context(self):
        require_pipe = AsyncMock()
        run_sync = AsyncMock()

        with (
            patch(
                "app.routers.mcp.sync_connection.require_mcp_write_access",
                side_effect=ValueError("Workspace write access is required"),
            ),
            patch(
                "app.routers.mcp.sync_connection.require_pipe_in_collection",
                new=require_pipe,
            ),
            patch(
                "app.routers.mcp.sync_connection.run_connection_sync",
                new=run_sync,
            ),
        ):
            with self.assertRaisesRegex(ValueError, "write access"):
                await sync_connection("forecasting", 7)

        require_pipe.assert_not_awaited()
        run_sync.assert_not_awaited()

    async def test_refreshes_a_pipe_in_the_selected_collection(self):
        sync_result = {
            "ok": True,
            "run_id": 41,
            "connection_id": 7,
            "destination_id": 2,
            "schema": "sales_forecast",
            "source_format": "google_sheets",
            "tables": [{"name": "orders", "columns": ["many", "values"]}],
            "table_count": 3,
            "row_count": 1200,
            "load_ids": ["load-1"],
            "completed_at": "2026-09-07T10:00:00+00:00",
        }

        with (
            patch(
                "app.routers.mcp.sync_connection.require_mcp_write_access"
            ) as require_write,
            patch(
                "app.routers.mcp.sync_connection.require_pipe_in_collection",
                new=AsyncMock(return_value={"pipe_ids": [7]}),
            ) as require_pipe,
            patch(
                "app.routers.mcp.sync_connection.run_connection_sync",
                new=AsyncMock(return_value=sync_result),
            ) as run_sync,
        ):
            result = await sync_connection("forecasting", 7)

        require_write.assert_called_once_with()
        require_pipe.assert_awaited_once_with("forecasting", 7)
        run_sync.assert_awaited_once_with(7, trigger="mcp")
        self.assertEqual(
            {
                "ok": True,
                "run_id": 41,
                "destination": {"id": 2, "schema": "sales_forecast"},
                "source_format": "google_sheets",
                "table_count": 3,
                "row_count": 1200,
                "completed_at": "2026-09-07T10:00:00+00:00",
            },
            result,
        )
        self.assertNotIn("tables", result)
        self.assertNotIn("load_ids", result)

    async def test_translates_sync_conflicts_for_mcp_clients(self):
        with (
            patch("app.routers.mcp.sync_connection.require_mcp_write_access"),
            patch(
                "app.routers.mcp.sync_connection.require_pipe_in_collection",
                new=AsyncMock(return_value={"pipe_ids": [7]}),
            ),
            patch(
                "app.routers.mcp.sync_connection.run_connection_sync",
                new=AsyncMock(
                    side_effect=HTTPException(
                        409,
                        "A sync is already running for this connection",
                    )
                ),
            ),
        ):
            with self.assertRaisesRegex(ValueError, "already running"):
                await sync_connection("forecasting", 7)


if __name__ == "__main__":
    unittest.main()
