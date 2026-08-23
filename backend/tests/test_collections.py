import json
import tempfile
import unittest

from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app import collection_service
from app.cube import model as cube_model
from app.routers.mcp.common import RootPathAsSlash


class CollectionServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.connection_dir = root / "connections"
        self.model_dir = root / "model"
        self.connection_dir.mkdir()
        (self.model_dir / "generated" / "connections").mkdir(parents=True)

        (self.connection_dir / "january_bank.manifest.yaml").write_text(
            """
generated_at: '2026-08-23'
tables:
  - name: transactions
    columns:
      - name: amount
        type: numeric
""".strip()
            + "\n",
            encoding="utf-8",
        )
        (self.model_dir / "generated" / "connections" / "january_bank.yaml").write_text(
            """
cubes:
  - name: january_bank_transactions
    sql_table: january_bank.transactions
    meta:
      settra:
        connection_id: 7
views:
  - name: finance_activity
    cubes:
      - join_path: january_bank_transactions
        includes: '*'
""".strip()
            + "\n",
            encoding="utf-8",
        )

        self.patches = [
            patch.object(
                collection_service,
                "CONNECTION_CONFIG_DIR",
                self.connection_dir,
            ),
            patch.object(cube_model, "CUBE_MODEL_DIR", self.model_dir),
        ]
        for active_patch in self.patches:
            active_patch.start()
            self.addCleanup(active_patch.stop)

    async def asyncTearDown(self):
        self.temp_dir.cleanup()

    async def test_collection_derives_destination_tables_and_cubes_from_pipes(self):
        row = {
            "id": 1,
            "name": "Finance",
            "slug": "finance",
            "description": "Finance data",
            "agent_instructions": "Use approved account categories.",
            "created_at": "2026-08-23",
            "updated_at": "2026-08-23",
        }
        pipe = collection_service._pipe_summary(
            {
                "id": 7,
                "name": "January bank",
                "slug": "january_bank",
                "status": "active",
                "last_synced_at": "2026-08-23",
            }
        )
        with patch.object(
            collection_service,
            "_collection_and_pipes",
            AsyncMock(return_value=(row, [pipe])),
        ):
            collection = await collection_service.get_collection(1)

        self.assertEqual("finance", collection["slug"])
        self.assertEqual([7], collection["pipe_ids"])
        self.assertEqual(1, collection["table_count"])
        self.assertEqual("january_bank", collection["tables"][0]["schema"])
        self.assertEqual(
            ["finance_activity", "january_bank_transactions"],
            collection["cube_names"],
        )
        self.assertEqual("/mcp/collections/finance", collection["mcp_path"])

    async def test_collection_rejects_unknown_pipe_ids(self):
        class EmptyDatabase:
            async def fetch(self, *_args):
                return []

        @asynccontextmanager
        async def empty_database():
            yield EmptyDatabase()

        with self.assertRaisesRegex(Exception, "Unknown pipe IDs: 99"):
            with patch.object(collection_service, "db_connection", empty_database):
                await collection_service._validated_pipe_ids([99])


class PinnedCollectionPathTests(unittest.IsolatedAsyncioTestCase):
    async def test_pinned_path_injects_collection_into_scoped_tool_calls(self):
        captured: dict = {}

        async def app(scope, receive, send):
            captured["scope"] = scope
            captured["request"] = json.loads((await receive())["body"])

        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "list_cubes",
                    "arguments": {"collection": "other"},
                },
            }
        ).encode()
        delivered = False

        async def receive():
            nonlocal delivered
            if delivered:
                return {"type": "http.disconnect"}
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(_message):
            return None

        wrapper = RootPathAsSlash(app)
        await wrapper(
            {
                "type": "http",
                "method": "POST",
                "path": "/collections/finance",
                "raw_path": b"/collections/finance",
                "headers": [],
            },
            receive,
            send,
        )

        self.assertEqual("/", captured["scope"]["path"])
        self.assertEqual(
            "finance",
            captured["request"]["params"]["arguments"]["collection"],
        )


if __name__ == "__main__":
    unittest.main()
