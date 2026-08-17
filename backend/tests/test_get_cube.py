import json
import tempfile
import unittest

from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.cube.model import authored_definition_index, source_definition_index
from app.cube.projection import CubeProjectionInput, SemanticResponseProjector
from app.cube.query import cube_by_name

projector = SemanticResponseProjector()


def _compiled_charge_cube():
    return {
        "name": "sales_sheet_orders",
        "title": "Charges",
        "shortTitle": "Charges",
        "type": "cube",
        "description": "Order rows from the Sales worksheet.\n\nLong compiled guidance.",
        "public": True,
        "isVisible": True,
        "measures": [
            {
                "name": "sales_sheet_orders.successful_charges",
                "title": "Successful Charges",
                "shortTitle": "Successful Charges",
                "type": "number",
                "aggType": "count",
                "description": "Count of succeeded charges.",
                "format": {"type": "number"},
                "drillMembers": [],
                "drillMembersGrouped": {"measures": [], "dimensions": []},
                "cumulative": False,
                "cumulativeTotal": False,
                "public": True,
                "isVisible": True,
            },
            {
                "name": "sales_sheet_orders.hidden_amount",
                "type": "number",
                "aggType": "sum",
                "public": False,
                "isVisible": False,
                "cumulative": True,
            },
        ],
        "dimensions": [
            {
                "name": "sales_sheet_orders.id",
                "title": "Charge ID",
                "type": "string",
                "primaryKey": True,
                "suggestFilterValues": True,
                "public": True,
                "isVisible": True,
            },
            {
                "name": "sales_sheet_orders.customer",
                "title": "Customer",
                "type": "string",
                "primaryKey": False,
                "suggestFilterValues": True,
            },
            {
                "name": "sales_sheet_orders.status",
                "title": "Status",
                "type": "string",
                "suggestFilterValues": False,
            },
        ],
        "segments": [],
        "joins": [],
        "hierarchies": [],
        "folders": [],
    }


def _authored_charge_source():
    return {
        "path": "generated/connections/sales_sheet.yaml",
        "source_type": "generated_connection",
        "definition": {
            "name": "sales_sheet_orders",
            "title": "Charges",
            "description": (
                "Order rows from the Sales worksheet.\n\n"
                "Amount values are stored in minor currency units."
            ),
            "sql_table": '"sales_sheet"."orders"',
            "meta": {"settra": {"connection_id": 6}},
            "measures": [
                {
                    "name": "successful_charges",
                    "title": "Successful Charges",
                    "description": "Count of succeeded charges.",
                    "type": "count",
                    "filters": [{"sql": "status = 'succeeded'"}],
                },
                {
                    "name": "hidden_amount",
                    "type": "sum",
                    "sql": "amount / 100.0",
                    "format": "currency",
                    "public": False,
                    "shown": False,
                },
            ],
            "dimensions": [
                {
                    "name": "id",
                    "title": "Charge ID",
                    "sql": "id",
                    "type": "string",
                    "primary_key": True,
                    "description": "Charge id.",
                },
                {
                    "name": "customer",
                    "sql": "coalesce(substring(customer from 'ID:([^ ]+)'), customer)",
                    "type": "string",
                    "meta": {"references": "sales_sheet_customers.id"},
                },
                {"name": "status", "sql": "status", "type": "string"},
            ],
            "segments": [
                {
                    "name": "successful_only",
                    "title": "Successful only",
                    "sql": "status = 'succeeded'",
                }
            ],
            "joins": [
                {
                    "name": "sales_sheet_customers",
                    "relationship": "many_to_one",
                    "sql": "{CUBE}.customer = {sales_sheet_customers}.id",
                }
            ],
        },
    }


class CompactCubeDefinitionTests(unittest.TestCase):
    def test_compacts_ui_metadata_and_preserves_semantic_logic(self):
        result = projector.cube(
            CubeProjectionInput(
                compiled=_compiled_charge_cube(),
                authored_source=_authored_charge_source(),
            )
        )

        self.assertEqual("sales_sheet_orders", result["name"])
        self.assertEqual("Order rows from the Sales worksheet.", result["description"])
        self.assertEqual(
            {
                "type": "generated_connection",
                "path": "generated/connections/sales_sheet.yaml",
                "connection_id": 6,
                "table": "sales_sheet.orders",
            },
            result["source"],
        )
        self.assertEqual(
            {
                "type": "count",
                "description": "Count of succeeded charges.",
                "filter": "status = 'succeeded'",
            },
            result["measures"]["successful_charges"],
        )
        self.assertEqual(
            {
                "type": "sum",
                "sql": "amount / 100.0",
                "public": False,
                "visible": False,
                "format": "currency",
                "cumulative": True,
            },
            result["measures"]["hidden_amount"],
        )
        self.assertEqual(
            {"type": "string", "description": "Charge id.", "primary_key": True},
            result["dimensions"]["id"],
        )
        self.assertEqual(
            {
                "type": "string",
                "sql": "coalesce(substring(customer from 'ID:([^ ]+)'), customer)",
                "references": "sales_sheet_customers.id",
            },
            result["dimensions"]["customer"],
        )
        self.assertEqual(
            {"type": "string", "suggest_filter_values": False},
            result["dimensions"]["status"],
        )
        self.assertEqual(
            {"successful_only": "status = 'succeeded'"},
            result["segments"],
        )
        self.assertEqual(
            {
                "sales_sheet_customers": {
                    "relationship": "many_to_one",
                    "sql": "{CUBE}.customer = {sales_sheet_customers}.id",
                }
            },
            result["relationships"],
        )

        serialized = json.dumps(result)
        self.assertNotIn("source_definition", result)
        self.assertNotIn("shortTitle", serialized)
        self.assertNotIn("drillMembers", serialized)
        self.assertNotIn("sales_sheet_orders.successful_charges", serialized)

    def test_compact_projection_is_materially_smaller_than_the_old_shape(self):
        cube = _compiled_charge_cube()
        source = _authored_charge_source()
        old_shape = {**cube, "source_definition": source}
        compact = projector.cube(
            CubeProjectionInput(compiled=cube, authored_source=source)
        )

        self.assertLess(len(json.dumps(compact)), len(json.dumps(old_shape)) / 2)


class AuthoredDefinitionIndexTests(unittest.TestCase):
    def test_indexes_exact_definition_and_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            model_dir = Path(directory)
            generated = model_dir / "generated" / "connections"
            generated.mkdir(parents=True)
            (generated / "sales_sheet.yaml").write_text(
                """
cubes:
- name: orders
  sql_table: '"sales_sheet"."orders"'
  measures:
  - name: charges
    type: count
""".strip(),
                encoding="utf-8",
            )

            with patch("app.cube.model.CUBE_MODEL_DIR", model_dir):
                result = authored_definition_index()

        self.assertEqual(
            "generated/connections/sales_sheet.yaml",
            result["orders"]["path"],
        )
        self.assertEqual(
            "generated_connection",
            result["orders"]["source_type"],
        )
        self.assertEqual(
            "count",
            result["orders"]["definition"]["measures"][0]["type"],
        )

    def test_source_index_preserves_join_contracts_for_discovery(self):
        with tempfile.TemporaryDirectory() as directory:
            model_dir = Path(directory)
            generated = model_dir / "generated" / "connections"
            generated.mkdir(parents=True)
            (generated / "sales_sheet.yaml").write_text(
                """
cubes:
- name: customers
  sql_table: '"sales_sheet"."customers"'
  joins:
  - name: orders
    sql: "{CUBE}.id = {orders}.customer"
    relationship: one_to_many
""".strip(),
                encoding="utf-8",
            )

            with patch("app.cube.model.CUBE_MODEL_DIR", model_dir):
                result = source_definition_index()

        self.assertEqual(
            {
                "orders": {
                    "sql": "{CUBE}.id = {orders}.customer",
                    "relationship": "one_to_many",
                }
            },
            result["customers"]["joins"],
        )


class CubeByNameTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_the_compact_projection(self):
        with (
            patch(
                "app.cube.query.load_cube_meta",
                new=AsyncMock(return_value={"cubes": [_compiled_charge_cube()]}),
            ),
            patch(
                "app.cube.query.authored_definition_index",
                return_value={"sales_sheet_orders": _authored_charge_source()},
            ),
        ):
            result = await cube_by_name("sales_sheet_orders")

        self.assertEqual("sales_sheet_orders", result["name"])
        self.assertNotIn("source_definition", result)
        self.assertIn("successful_charges", result["measures"])


if __name__ == "__main__":
    unittest.main()
