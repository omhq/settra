import unittest

from contextlib import asynccontextmanager
from unittest.mock import patch

from app.mcp_request_log import payload_size, record_mcp_request, tool_result_size


class ToolResultSizeTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_payload_bytes_and_logical_token_bytes_are_recorded_separately(self):
        class Transaction:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

        class RecordingDatabase:
            def __init__(self):
                self.calls = []

            def transaction(self):
                return Transaction()

            async def execute(self, query, *params):
                self.calls.append((query, params))

        database = RecordingDatabase()

        @asynccontextmanager
        async def recording_database():
            yield database

        with patch("app.mcp_request_log.db_connection", recording_database):
            await record_mcp_request(
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

        insert_params = database.calls[0][1]
        self.assertEqual((12_000, 1_000), (insert_params[7], insert_params[9]))


if __name__ == "__main__":
    unittest.main()
