import unittest

from unittest.mock import AsyncMock, patch

from app.agent.consts import TABLE_SAMPLE_VALUE_MAX_CHARS
from app.cube.projection import (
    SemanticResponseProjector,
    TableSampleProjectionInput,
)
from app.routers.connection_metadata import _json_rows
from app.routers.mcp.sample_connection_table import sample_table

projector = SemanticResponseProjector()


def _raw_sample():
    customer = "{APIResource:{LastResponse:<nil>} Address:<nil> Balance:0 " * 8

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
        "limit": 5,
        "columns": [
            {
                "name": "customer",
                "type": "text",
                "nullable": True,
                "description": "Expanded customer value.",
            },
            {
                "name": "amount",
                "type": "bigint",
                "nullable": False,
                "description": "Charge amount.",
            },
            {
                "name": "status",
                "type": "text",
                "nullable": True,
                "description": "Charge status.",
            },
        ],
        "rows": [
            {
                "customer": customer[: TABLE_SAMPLE_VALUE_MAX_CHARS - 1] + "…",
                "amount": 49_900,
                "status": "failed",
            },
            {
                "customer": "cus_123",
                "amount": 2_000,
                "status": "succeeded",
            },
        ],
        "truncated_values": ["customer"],
    }


class SampleValueSerializationTests(unittest.TestCase):
    def test_records_columns_whose_scalar_values_were_truncated(self):
        long_customer = "{APIResource:{LastResponse:<nil>} " * 20
        rows, truncated = _json_rows(
            [{"customer": long_customer, "amount": 49_900}],
            [
                {"name": "customer"},
                {"name": "amount"},
            ],
        )

        self.assertEqual(["customer"], truncated)
        self.assertEqual(TABLE_SAMPLE_VALUE_MAX_CHARS, len(rows[0]["customer"]))
        self.assertTrue(rows[0]["customer"].endswith("…"))
        self.assertEqual(49_900, rows[0]["amount"])


class TableSampleProjectionTests(unittest.TestCase):
    def test_returns_column_names_once_and_positional_rows(self):
        result = projector.table_sample(
            TableSampleProjectionInput(response=_raw_sample())
        )

        self.assertEqual(["customer", "amount", "status"], result["columns"])
        self.assertEqual(
            [
                [_raw_sample()["rows"][0]["customer"], 49_900, "failed"],
                ["cus_123", 2_000, "succeeded"],
            ],
            result["rows"],
        )
        self.assertEqual(2, result["row_count"])
        self.assertTrue(result["truncated"])
        self.assertEqual(["customer"], result["truncated_values"])
        self.assertNotIn("connection", result)
        self.assertNotIn("table", result)
        self.assertNotIn("limit", result)

    def test_omits_default_truncation_fields(self):
        sample = _raw_sample()
        sample["truncated_values"] = []

        result = projector.table_sample(TableSampleProjectionInput(response=sample))

        self.assertNotIn("truncated", result)
        self.assertNotIn("truncated_values", result)


class SampleConnectionTableToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_uses_the_compact_projection(self):
        load_sample = AsyncMock(return_value=_raw_sample())

        with patch(
            "app.routers.mcp.sample_connection_table.sample_connection_table",
            new=load_sample,
        ):
            result = await sample_table(
                connection_id=6,
                table_name="orders",
                limit=5,
                columns=["customer", "amount", "status"],
            )

        self.assertEqual(["customer", "amount", "status"], result["columns"])
        self.assertEqual(2, result["row_count"])
        self.assertEqual(["customer"], result["truncated_values"])


if __name__ == "__main__":
    unittest.main()
