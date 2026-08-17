import unittest

from unittest.mock import AsyncMock, patch

from app.cube.projection import (
    PROFILE_DESCRIPTION_MAX_CHARS,
    SemanticResponseProjector,
    TableProfileProjectionInput,
)
from app.routers.mcp.profile_connection_table import profile_table

projector = SemanticResponseProjector()


def _raw_profile():
    return {
        "connection": {
            "id": 6,
            "name": "Sales Sheet",
            "slug": "sales_sheet",
            "plugin": "googlesheets",
            "status": "connected",
        },
        "table": {
            "name": "orders",
            "description": "Order rows from the Sales worksheet.",
            "metadata": {},
        },
        "profile_scope": "sampled_rows",
        "sampled_row_count": 16,
        "sample_limit": 500,
        "columns": [
            {
                "name": "status",
                "type": "text",
                "nullable": True,
                "description": "Charge status.",
                "sampled_count": 16,
                "null_count": 0,
                "empty_string_count": 0,
                "distinct_sample_count": 2,
                "inferred_type": "string",
                "example_values": ["succeeded", "failed"],
            },
            {
                "name": "failure_code",
                "type": "varchar(255)",
                "nullable": True,
                "description": "x" * 1_000,
                "sampled_count": 16,
                "null_count": 15,
                "empty_string_count": 0,
                "distinct_sample_count": 1,
                "inferred_type": "string",
                "example_values": ["card_declined"],
            },
            {
                "name": "email",
                "type": "text",
                "nullable": True,
                "description": "Customer email.",
                "sampled_count": 16,
                "null_count": 1,
                "empty_string_count": 2,
                "distinct_sample_count": 3,
                "inferred_type": "email",
                "example_values": ["customer@example.com"],
            },
        ],
    }


class TableProfileProjectionTests(unittest.TestCase):
    def test_returns_a_compact_map_keyed_by_column_name(self):
        result = projector.table_profile(
            TableProfileProjectionInput(response=_raw_profile())
        )

        self.assertEqual(
            {
                "sampled_rows": 16,
                "columns": {
                    "status": {
                        "type": "string",
                        "nulls": 0,
                        "distinct": 2,
                        "examples": ["succeeded", "failed"],
                    },
                    "failure_code": {
                        "type": "string",
                        "nulls": 15,
                        "distinct": 1,
                        "examples": ["card_declined"],
                    },
                    "email": {
                        "source_type": "text",
                        "inferred_type": "email",
                        "nulls": 1,
                        "distinct": 3,
                        "empty_strings": 2,
                        "examples": ["customer@example.com"],
                    },
                },
            },
            result,
        )
        self.assertNotIn("connection", result)
        self.assertNotIn("table", result)
        self.assertNotIn("sample_limit", result)

    def test_descriptions_are_opt_in_and_bounded(self):
        compact = projector.table_profile(
            TableProfileProjectionInput(response=_raw_profile())
        )
        described = projector.table_profile(
            TableProfileProjectionInput(
                response=_raw_profile(),
                include_descriptions=True,
            )
        )

        self.assertNotIn("description", compact["columns"]["status"])
        self.assertEqual(
            "Charge status.", described["columns"]["status"]["description"]
        )
        long_description = described["columns"]["failure_code"]["description"]
        self.assertEqual(PROFILE_DESCRIPTION_MAX_CHARS, len(long_description))
        self.assertTrue(long_description.endswith("…"))

    def test_empty_examples_are_omitted_and_declared_type_survives_no_values(self):
        raw = _raw_profile()
        raw["columns"] = [
            {
                "name": "created",
                "type": "timestamp with time zone",
                "null_count": 16,
                "empty_string_count": 0,
                "distinct_sample_count": 0,
                "inferred_type": "unknown",
                "example_values": [],
            }
        ]

        result = projector.table_profile(TableProfileProjectionInput(response=raw))

        self.assertEqual(
            {"type": "time", "nulls": 16, "distinct": 0},
            result["columns"]["created"],
        )


class ProfileConnectionTableToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_projects_profile_and_honors_description_opt_in(self):
        load_profile = AsyncMock(return_value=_raw_profile())

        with patch(
            "app.routers.mcp.profile_connection_table.profile_connection_table",
            new=load_profile,
        ):
            result = await profile_table(
                connection_id=6,
                table_name="orders",
                limit=16,
                columns=["status", "failure_code"],
                include_descriptions=True,
            )

        self.assertEqual(16, result["sampled_rows"])
        self.assertEqual("Charge status.", result["columns"]["status"]["description"])
        self.assertEqual(16, load_profile.await_args.kwargs["limit"])
        self.assertEqual(
            ["status", "failure_code"], load_profile.await_args.kwargs["columns"]
        )


if __name__ == "__main__":
    unittest.main()
