import unittest

from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.cube.query import bounded_cube_meta, semantic_catalog
from app.routers.connection_metadata import connection_metadata_catalog


def _connection_metadata(*, table_count: int = 8, column_count: int = 15):
    return {
        "connection_id": 5,
        "slug": "pipeline_sheet",
        "plugin": "pipeline_sheet",
        "generated_at": "2026-07-01T00:00:00+00:00",
        "tables": {
            f"table_{table_index}": {
                "description": f"Table {table_index}",
                "metadata": {
                    "source": "fixture",
                    "nested": {"values": list(range(100))},
                },
                "columns": [
                    {
                        "name": f"column_{column_index}",
                        "type": "text",
                        "nullable": True,
                        "description": "x" * 1_000,
                    }
                    for column_index in range(column_count)
                ],
                "ddl": "CREATE TABLE ignored (" + ("x" * 50_000) + ")",
            }
            for table_index in range(table_count)
        },
    }


def _cube(index: int):
    return {
        "name": f"cube_{index}",
        "title": f"Cube {index}",
        "type": "cube",
        "description": "x" * 1_000,
        "measures": [
            {"name": f"cube_{index}.measure_{member_index}"}
            for member_index in range(20)
        ],
        "dimensions": [
            {"name": f"cube_{index}.dimension_{member_index}"}
            for member_index in range(20)
        ],
        "segments": [],
        "joins": [],
    }


def _authored_definition(definition: dict):
    return {
        definition["name"]: {
            "path": f"generated/connections/{definition['name']}.yaml",
            "source_type": "generated_connection",
            "definition": definition,
        }
    }


def _source_definition_with_joins(name: str):
    return {
        name: {
            "path": f"generated/connections/{name}.yaml",
            "source_type": "generated_connection",
            "joins": {
                "sales_sheet_orders": {
                    "sql": "{CUBE}.id = {sales_sheet_orders}.customer",
                    "relationship": "one_to_many",
                },
                "sales_sheet_forecast": {
                    "sql": "{CUBE}.id = {sales_sheet_forecast}.customer_id",
                    "relationship": "one_to_many",
                },
            },
        }
    }


class ConnectionMetadataCatalogTests(unittest.TestCase):
    def test_default_is_five_tables_with_bounded_column_pages(self):
        result = connection_metadata_catalog(_connection_metadata())

        self.assertEqual(5, len(result["tables"]))
        self.assertEqual({"next_cursor": 5, "total": 8}, result["page"])
        self.assertNotIn("generated_at", result)
        self.assertNotIn("filters", result)
        self.assertNotIn("table_count", result)

        for table in result["tables"]:
            self.assertEqual(15, table["column_count"])
            self.assertTrue(table["source_metadata_available"])
            self.assertEqual(10, len(table["columns"]))
            self.assertEqual(
                {"next_column_cursor": 10, "total": 15},
                table["column_page"],
            )
            self.assertNotIn("source_metadata", table)
            self.assertNotIn("ddl", table)

    def test_empty_include_returns_table_summaries_only(self):
        result = connection_metadata_catalog(_connection_metadata(), include=[])

        for table in result["tables"]:
            self.assertNotIn("columns", table)
            self.assertNotIn("column_page", table)

    def test_columns_are_opt_in_and_independently_paginated(self):
        result = connection_metadata_catalog(
            _connection_metadata(table_count=1),
            include=["columns"],
            column_cursor=10,
            column_limit=3,
        )
        table = result["tables"][0]

        self.assertEqual(
            ["column_10", "column_11", "column_12"],
            [column["name"] for column in table["columns"]],
        )
        self.assertEqual(
            {"next_column_cursor": 13, "total": 15},
            table["column_page"],
        )
        self.assertLessEqual(len(table["columns"][0]["description"]), 300)
        self.assertTrue(table["columns"][0]["description_truncated"])

    def test_source_metadata_availability_is_present_only_when_true(self):
        metadata = _connection_metadata(table_count=2)
        metadata["tables"]["table_0"].pop("metadata")

        result = connection_metadata_catalog(metadata)

        self.assertNotIn("source_metadata_available", result["tables"][0])
        self.assertTrue(result["tables"][1]["source_metadata_available"])

    def test_empty_optional_metadata_is_omitted(self):
        metadata = _connection_metadata(table_count=1, column_count=1)
        table = metadata["tables"]["table_0"]
        table["description"] = ""
        table["metadata"] = {}
        table["columns"][0]["description"] = ""

        result = connection_metadata_catalog(
            metadata,
            include=["columns", "source_metadata"],
        )
        projected = result["tables"][0]

        self.assertNotIn("description", projected)
        self.assertNotIn("source_metadata_available", projected)
        self.assertNotIn("source_metadata", projected)
        self.assertNotIn("description", projected["columns"][0])

    def test_search_matches_column_names_and_source_metadata_is_bounded(self):
        metadata = _connection_metadata(table_count=2)
        metadata["tables"]["table_1"]["columns"][0]["name"] = "customer_email"
        result = connection_metadata_catalog(
            metadata,
            search="customer email",
            include=["source_metadata"],
        )

        self.assertEqual(["table_1"], [table["name"] for table in result["tables"]])
        self.assertIn("source_metadata", result["tables"][0])
        self.assertLess(len(str(result["tables"][0]["source_metadata"])), 2_000)

    def test_rejects_requests_above_hard_limits(self):
        with self.assertRaises(HTTPException):
            connection_metadata_catalog(_connection_metadata(), limit=6)

        with self.assertRaises(HTTPException):
            connection_metadata_catalog(_connection_metadata(), column_limit=11)


class CubeCatalogTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_is_five_cubes_without_member_arrays(self):
        meta = {"cubes": [_cube(index) for index in range(8)], "compilerId": "test"}
        sources = {
            f"cube_{index}": {
                "path": f"generated/connections/source_{index}.yaml",
                "source_type": "generated_connection",
            }
            for index in range(8)
        }

        with (
            patch("app.cube.query.load_cube_meta", new=AsyncMock(return_value=meta)),
            patch("app.cube.query.source_definition_index", return_value=sources),
            patch("app.cube.query.authored_definition_index", return_value={}),
        ):
            result = await semantic_catalog()

        self.assertEqual(5, len(result["cubes"]))
        self.assertEqual({"next_cursor": 5, "total": 8}, result["page"])
        self.assertNotIn("cube_count", result)
        self.assertNotIn("filters", result)
        self.assertNotIn("compiler_id", result)

        for index, cube in enumerate(result["cubes"]):
            self.assertNotIn("measures", cube)
            self.assertNotIn("dimensions", cube)
            self.assertLessEqual(len(cube["description"]), 160)
            self.assertNotIn("description_truncated", cube)
            self.assertEqual(
                {
                    "measures": 20,
                    "dimensions": 20,
                    "segments": 0,
                    "joins": 0,
                },
                cube["members"],
            )
            self.assertEqual(f"source_{index}", cube["source"])

    async def test_member_previews_are_opt_in_and_capped(self):
        meta = {"cubes": [_cube(0)], "compilerId": "test"}

        with (
            patch("app.cube.query.load_cube_meta", new=AsyncMock(return_value=meta)),
            patch("app.cube.query.source_definition_index", return_value={}),
            patch("app.cube.query.authored_definition_index", return_value={}),
        ):
            result = await semantic_catalog(include=["measures"], member_limit=3)

        self.assertEqual(3, len(result["cubes"][0]["measures"]))
        self.assertEqual(20, result["cubes"][0]["members"]["measures"])
        self.assertEqual(
            ["measure_0", "measure_1", "measure_2"],
            [member["name"] for member in result["cubes"][0]["measures"]],
        )
        self.assertNotIn("collection_page", result["cubes"][0])

    async def test_multi_entity_search_returns_ranked_partial_matches(self):
        meta = {
            "cubes": [
                {**_cube(0), "name": "pipeline", "title": "Deals"},
                {**_cube(1), "name": "customers", "title": "Customers"},
                {**_cube(2), "name": "invoices", "title": "Invoices"},
                {
                    **_cube(3),
                    "name": "forecast",
                    "title": "Subscriptions",
                },
                {**_cube(4), "name": "orders", "title": "Charges"},
            ],
            "compilerId": "test",
        }

        with (
            patch("app.cube.query.load_cube_meta", new=AsyncMock(return_value=meta)),
            patch("app.cube.query.source_definition_index", return_value={}),
            patch("app.cube.query.authored_definition_index", return_value={}),
        ):
            result = await semantic_catalog(
                search="customer invoice forecast order",
                limit=5,
            )

        self.assertEqual(
            [
                "customers",
                "invoices",
                "forecast",
                "orders",
            ],
            [cube["name"] for cube in result["cubes"]],
        )
        self.assertEqual({"next_cursor": None, "total": 4}, result["page"])

    async def test_authored_joins_are_discoverable_when_compiled_joins_are_empty(self):
        meta = {
            "cubes": [
                {
                    **_cube(1),
                    "name": "sales_sheet_customers",
                    "title": "Customers",
                    "joins": [],
                }
            ],
            "compilerId": "test",
        }
        authored = _authored_definition(
            {
                "name": "sales_sheet_customers",
                "joins": [
                    {
                        "name": "sales_sheet_orders",
                        "sql": "{CUBE}.id = {sales_sheet_orders}.customer",
                        "relationship": "one_to_many",
                    },
                    {
                        "name": "sales_sheet_forecast",
                        "sql": "{CUBE}.id = {sales_sheet_forecast}.customer_id",
                        "relationship": "one_to_many",
                    },
                ],
            }
        )

        with (
            patch("app.cube.query.load_cube_meta", new=AsyncMock(return_value=meta)),
            patch("app.cube.query.source_definition_index", return_value={}),
            patch("app.cube.query.authored_definition_index", return_value=authored),
        ):
            result = await semantic_catalog(include=["joins"])

        cube = result["cubes"][0]
        self.assertEqual(2, cube["members"]["joins"])
        self.assertEqual(
            ["sales_sheet_orders", "sales_sheet_forecast"],
            [join["name"] for join in cube["joins"]],
        )
        self.assertEqual(
            ["one_to_many", "one_to_many"],
            [join["relationship"] for join in cube["joins"]],
        )

    async def test_source_joins_are_discoverable_when_compiled_joins_are_empty(self):
        meta = {
            "cubes": [
                {
                    **_cube(1),
                    "name": "sales_sheet_customers",
                    "title": "Customers",
                    "joins": [],
                }
            ],
            "compilerId": "test",
        }

        with (
            patch("app.cube.query.load_cube_meta", new=AsyncMock(return_value=meta)),
            patch(
                "app.cube.query.source_definition_index",
                return_value=_source_definition_with_joins("sales_sheet_customers"),
            ),
            patch("app.cube.query.authored_definition_index", return_value={}),
        ):
            result = await semantic_catalog(include=["joins"])

        cube = result["cubes"][0]
        self.assertEqual(2, cube["members"]["joins"])
        self.assertEqual(
            ["sales_sheet_orders", "sales_sheet_forecast"],
            [join["name"] for join in cube["joins"]],
        )
        self.assertEqual(
            ["one_to_many", "one_to_many"],
            [join["relationship"] for join in cube["joins"]],
        )


class CubeMetaTests(unittest.IsolatedAsyncioTestCase):
    async def test_omits_defaults_echoes_and_duplicate_member_prefixes(self):
        meta = {
            "compilerId": None,
            "cubes": [
                {
                    "name": "orders",
                    "title": "Charges",
                    "description": "x" * 1_000,
                    "type": "cube",
                    "public": True,
                    "isVisible": True,
                    "measures": [
                        {
                            "name": "orders.count",
                            "title": "Count",
                            "shortTitle": "Count",
                            "description": "y" * 1_000,
                            "type": "number",
                            "aggType": "count",
                            "public": True,
                            "isVisible": True,
                            "primaryKey": False,
                            "filters": [],
                            "drillMembers": [],
                            "format": {},
                            "cumulative": False,
                            "cumulativeTotal": False,
                        },
                        {"name": "orders.total", "aggType": "sum"},
                    ],
                    "dimensions": [
                        {
                            "name": "orders.id",
                            "type": "string",
                            "primaryKey": True,
                            "public": False,
                            "isVisible": False,
                        }
                    ],
                    "segments": [],
                    "joins": [],
                    "hierarchies": [],
                    "folders": [],
                    "nestedFolders": [],
                }
            ],
        }

        with (
            patch("app.cube.query.load_cube_meta", new=AsyncMock(return_value=meta)),
            patch("app.cube.query.authored_definition_index", return_value={}),
            patch("app.cube.query.source_definition_index", return_value={}),
        ):
            result = await bounded_cube_meta(
                search="order",
                include=["measures", "dimensions"],
                cursor=0,
                limit=1,
                member_limit=1,
            )

        self.assertEqual({"next_cursor": None, "total": 1}, result["page"])
        self.assertNotIn("filters", result)
        self.assertNotIn("compiler_id", result)
        cube = result["cubes"][0]
        self.assertNotIn("public", cube)
        self.assertNotIn("isVisible", cube)
        self.assertNotIn("type", cube)
        self.assertEqual(300, len(cube["description"]))
        self.assertEqual({"measures": 2, "dimensions": 1}, cube["collection_counts"])
        self.assertEqual({"measures": {"total": 2}}, cube["collection_page"])
        measure = cube["measures"][0]
        self.assertEqual("count", measure["name"])
        self.assertNotIn("shortTitle", measure)
        self.assertNotIn("public", measure)
        self.assertNotIn("isVisible", measure)
        self.assertNotIn("primaryKey", measure)
        self.assertNotIn("filters", measure)
        self.assertNotIn("drillMembers", measure)
        self.assertNotIn("format", measure)
        self.assertNotIn("cumulative", measure)
        dimension = cube["dimensions"][0]
        self.assertEqual("id", dimension["name"])
        self.assertTrue(dimension["primaryKey"])
        self.assertFalse(dimension["public"])
        self.assertFalse(dimension["isVisible"])

    async def test_multi_entity_search_returns_ranked_partial_matches(self):
        meta = {
            "cubes": [
                {**_cube(0), "name": "pipeline", "title": "Deals"},
                {**_cube(1), "name": "customers", "title": "Customers"},
                {**_cube(2), "name": "invoices", "title": "Invoices"},
                {
                    **_cube(3),
                    "name": "forecast",
                    "title": "Subscriptions",
                },
                {**_cube(4), "name": "orders", "title": "Charges"},
            ],
        }

        with (
            patch("app.cube.query.load_cube_meta", new=AsyncMock(return_value=meta)),
            patch("app.cube.query.authored_definition_index", return_value={}),
            patch("app.cube.query.source_definition_index", return_value={}),
        ):
            result = await bounded_cube_meta(
                search="customer invoice forecast order",
                limit=10,
            )

        self.assertEqual(
            [
                "customers",
                "invoices",
                "forecast",
                "orders",
            ],
            [cube["name"] for cube in result["cubes"]],
        )
        self.assertEqual({"next_cursor": None, "total": 4}, result["page"])

    async def test_authored_joins_are_returned_when_compiled_joins_are_empty(self):
        meta = {
            "cubes": [
                {
                    **_cube(1),
                    "name": "sales_sheet_customers",
                    "title": "Customers",
                    "joins": [],
                }
            ]
        }
        authored = _authored_definition(
            {
                "name": "sales_sheet_customers",
                "joins": [
                    {
                        "name": "sales_sheet_orders",
                        "sql": "{CUBE}.id = {sales_sheet_orders}.customer",
                        "relationship": "one_to_many",
                    },
                    {
                        "name": "sales_sheet_forecast",
                        "sql": "{CUBE}.id = {sales_sheet_forecast}.customer_id",
                        "relationship": "one_to_many",
                    },
                ],
            }
        )

        with (
            patch("app.cube.query.load_cube_meta", new=AsyncMock(return_value=meta)),
            patch("app.cube.query.authored_definition_index", return_value=authored),
            patch("app.cube.query.source_definition_index", return_value={}),
        ):
            result = await bounded_cube_meta(include=["joins"], limit=1)

        cube = result["cubes"][0]
        self.assertEqual(2, cube["collection_counts"]["joins"])
        self.assertEqual(
            ["sales_sheet_orders", "sales_sheet_forecast"],
            [join["name"] for join in cube["joins"]],
        )
        self.assertEqual(
            ["one_to_many", "one_to_many"],
            [join["relationship"] for join in cube["joins"]],
        )

    async def test_source_joins_are_returned_when_compiled_joins_are_empty(self):
        meta = {
            "cubes": [
                {
                    **_cube(1),
                    "name": "sales_sheet_customers",
                    "title": "Customers",
                    "joins": [],
                }
            ]
        }

        with (
            patch("app.cube.query.load_cube_meta", new=AsyncMock(return_value=meta)),
            patch("app.cube.query.authored_definition_index", return_value={}),
            patch(
                "app.cube.query.source_definition_index",
                return_value=_source_definition_with_joins("sales_sheet_customers"),
            ),
        ):
            result = await bounded_cube_meta(include=["joins"], limit=1)

        cube = result["cubes"][0]
        self.assertEqual(2, cube["collection_counts"]["joins"])
        self.assertEqual(
            ["sales_sheet_orders", "sales_sheet_forecast"],
            [join["name"] for join in cube["joins"]],
        )
        self.assertEqual(
            ["one_to_many", "one_to_many"],
            [join["relationship"] for join in cube["joins"]],
        )


if __name__ == "__main__":
    unittest.main()
