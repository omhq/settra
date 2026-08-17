import asyncio
import sqlite3
import tempfile
import unittest

from pathlib import Path
from unittest.mock import patch

from app.mcp_request_log import payload_size, record_mcp_request, tool_result_size


class ToolResultSizeTests(unittest.TestCase):
    def test_structured_result_is_not_counted_twice(self):
        structured = {"rows": [{"id": 1}, {"id": 2}]}
        content = [
            {
                "type": "text",
                "text": '{\n  "rows": [\n    {"id": 1},\n    {"id": 2}\n  ]\n}',
            }
        ]
        result = (content, structured)

        self.assertEqual(payload_size(structured), tool_result_size(result))
        self.assertLess(tool_result_size(result), payload_size(result))

    def test_text_content_is_used_when_structured_result_is_absent(self):
        content = [{"type": "text", "text": "plain text result"}]

        self.assertEqual(payload_size(content), tool_result_size((content, None)))

    def test_non_tuple_results_keep_existing_behavior(self):
        result = {"ok": True}

        self.assertEqual(payload_size(result), tool_result_size(result))

    def test_payload_bytes_and_logical_token_bytes_are_recorded_separately(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "requests.db"

            with sqlite3.connect(db_path) as db:
                db.execute("""
                    CREATE TABLE mcp_requests (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        request_id TEXT,
                        client_id TEXT,
                        kind TEXT NOT NULL,
                        name TEXT NOT NULL,
                        status TEXT NOT NULL,
                        duration_ms INTEGER NOT NULL,
                        request_bytes INTEGER NOT NULL,
                        response_bytes INTEGER NOT NULL,
                        estimated_input_tokens INTEGER NOT NULL,
                        estimated_output_tokens INTEGER NOT NULL,
                        error_type TEXT,
                        created_at TEXT NOT NULL DEFAULT (datetime('now'))
                    )
                    """)

            with patch("app.mcp_request_log.DB_PATH", db_path):
                asyncio.run(
                    record_mcp_request(
                        request_id=None,
                        client_id=None,
                        kind="tool",
                        name="example",
                        status="success",
                        duration_ms=1,
                        request_bytes=40,
                        response_bytes=12_000,
                        response_token_bytes=4_000,
                    )
                )

            with sqlite3.connect(db_path) as db:
                row = db.execute("""
                    SELECT response_bytes, estimated_output_tokens
                    FROM mcp_requests
                    """).fetchone()

        self.assertEqual((12_000, 1_000), row)


if __name__ == "__main__":
    unittest.main()
