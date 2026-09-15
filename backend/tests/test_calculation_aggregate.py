import unittest

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

from app.calculations.aggregate import (
    AggregateExecution,
    AggregateSource,
    _connection_record,
    compile_aggregate_query,
    validate_aggregate_query,
)
from app.calculations.executor import execute_definition
from app.calculations.graph import validate_graph
from app.calculations.models import AggregateQueryNode
from app.calculations.parser import parse_calculation
from app.calculations.service import validate_calculation
from app.errors import InvalidInputError, ResourceNotFoundError


def aggregate_content(node: str, output: str = "aggregate") -> str:
    return f"""\
version: 1
name: aggregate_test
nodes:
{node}
outputs:
  result: {output}
"""


def aggregate_node(content: str) -> AggregateQueryNode:
    node = parse_calculation(content).nodes[0]
    assert isinstance(node, AggregateQueryNode)
    return node


class AggregateQueryCompilerTests(unittest.TestCase):
    def test_compiles_grouped_filtered_aggregates_with_a_sentinel_limit(self):
        node = aggregate_node(aggregate_content("""\
  - id: aggregate
    type: aggregate_query
    source:
      connection: sales
      table: orders
    measures:
      - name: total_revenue
        function: sum
        column: revenue
      - name: order_count
        function: count
    group_by: [region]
    filters:
      - column: status
        operator: equals
        value: paid
    limit: 2
"""))
        source = AggregateSource(
            schema="o41_sales",
            table="orders",
            column_types={
                "region": "text",
                "revenue": "numeric",
                "status": "text",
            },
        )

        sql, parameters, limit = compile_aggregate_query(node, source)

        self.assertEqual(
            """\
SELECT "region" AS "region", COALESCE(SUM("revenue"), 0) AS "total_revenue", COUNT(*) AS "order_count"
FROM "o41_sales"."orders"
WHERE "status" = $1
GROUP BY "region"
ORDER BY "region"
LIMIT $2""",
            sql,
        )
        self.assertEqual(["paid", 3], parameters)
        self.assertEqual(2, limit)

    def test_compiles_count_distinct_and_list_filters(self):
        node = aggregate_node(aggregate_content("""\
  - id: aggregate
    type: aggregate_query
    source: {connection: sales, table: orders}
    measures:
      - name: customers
        function: count_distinct
        column: customer_id
    filters:
      - column: region
        operator: in
        values: [Europe, Asia]
    result:
      kind: scalar
      member: customers
"""))
        source = AggregateSource(
            schema="o41_sales",
            table="orders",
            column_types={"customer_id": "text", "region": "text"},
        )

        sql, parameters, limit = compile_aggregate_query(node, source)

        self.assertIn('COUNT(DISTINCT "customer_id") AS "customers"', sql)
        self.assertIn('WHERE "region" IN ($1, $2)', sql)
        self.assertEqual(["Europe", "Asia"], parameters)
        self.assertIsNone(limit)

    def test_sum_uses_spreadsheet_zero_semantics_for_no_matching_rows(self):
        node = aggregate_node(aggregate_content("""\
  - id: aggregate
    type: aggregate_query
    source: {connection: sales, table: orders}
    measures:
      - {name: total, function: sum, column: revenue}
    result: {kind: scalar, member: total}
"""))
        source = AggregateSource(
            schema="o41_sales",
            table="orders",
            column_types={"revenue": "numeric"},
        )

        sql, _parameters, _limit = compile_aggregate_query(node, source)

        self.assertIn('COALESCE(SUM("revenue"), 0) AS "total"', sql)

    def test_rejects_unknown_and_non_numeric_columns(self):
        unknown = aggregate_node(aggregate_content("""\
  - id: aggregate
    type: aggregate_query
    source: {connection: sales, table: orders}
    measures:
      - {name: total, function: sum, column: missing}
    result: {kind: scalar, member: total}
"""))
        text_sum = aggregate_node(aggregate_content("""\
  - id: aggregate
    type: aggregate_query
    source: {connection: sales, table: orders}
    measures:
      - {name: total, function: sum, column: status}
    result: {kind: scalar, member: total}
"""))
        source = AggregateSource(
            schema="o41_sales",
            table="orders",
            column_types={"status": "text"},
        )

        with self.assertRaisesRegex(InvalidInputError, "unknown columns: missing"):
            compile_aggregate_query(unknown, source)
        with self.assertRaisesRegex(InvalidInputError, "requires numeric columns"):
            compile_aggregate_query(text_sum, source)

    def test_rejects_an_oversized_aggregate_table_before_execution(self):
        node = aggregate_node(aggregate_content("""\
  - id: aggregate
    type: aggregate_query
    source: {connection: sales, table: orders}
    measures:
      - {name: orders, function: count}
    group_by: [region]
    limit: 201
"""))
        source = AggregateSource(
            schema="o41_sales",
            table="orders",
            column_types={"region": "text"},
        )

        with self.assertRaisesRegex(InvalidInputError, "between 1 and 200"):
            compile_aggregate_query(node, source)

    def test_scalar_aggregate_rejects_grouping(self):
        with self.assertRaisesRegex(InvalidInputError, "cannot use group_by"):
            aggregate_node(aggregate_content("""\
  - id: aggregate
    type: aggregate_query
    source: {connection: sales, table: orders}
    measures:
      - {name: total, function: sum, column: revenue}
    group_by: [region]
    result: {kind: scalar, member: total}
"""))


class AggregateCalculationExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_aggregate_scalar_can_feed_a_formula(self):
        definition = parse_calculation(
            aggregate_content(
                """\
  - id: revenue
    type: aggregate_query
    source: {connection: sales, table: orders}
    measures:
      - {name: total_revenue, function: sum, column: revenue}
    result: {kind: scalar, member: total_revenue}
  - id: tax_rate
    type: value
    value: 0.2
  - id: tax
    type: formula
    inputs: {amount: revenue, rate: tax_rate}
    expression: amount * rate
""",
                output="tax",
            )
        )
        validate_graph(definition)
        aggregate = AggregateExecution(
            columns=["total_revenue"],
            rows=[{"total_revenue": "1250.50"}],
            row_count=1,
            has_more=False,
            limit=None,
        )

        with patch(
            "app.calculations.executor.execute_aggregate_query",
            new=AsyncMock(return_value=aggregate),
        ) as execute_aggregate:
            result = await execute_definition(
                definition,
                allowed_cube_names=set(),
                organization_id=41,
                allowed_connection_ids={17},
            )

        self.assertEqual(
            250.1,
            result["outputs"]["result"]["result"]["value"],
        )
        self.assertEqual(41, execute_aggregate.await_args.kwargs["organization_id"])


class AggregateCalculationServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_aggregate_source_must_belong_to_the_calculation_collection(self):
        node = aggregate_node(aggregate_content("""\
  - id: aggregate
    type: aggregate_query
    source: {connection: sales, table: orders}
    measures:
      - {name: orders, function: count}
"""))

        with patch(
            "app.calculations.aggregate._connection_record",
            new=AsyncMock(return_value={"id": 99}),
        ):
            with self.assertRaisesRegex(
                ResourceNotFoundError,
                "not in this calculation's collection",
            ):
                await validate_aggregate_query(
                    node,
                    organization_id=41,
                    allowed_connection_ids={17},
                )

    async def test_validation_resolves_the_source_in_the_active_organization(self):
        content = aggregate_content("""\
  - id: aggregate
    type: aggregate_query
    source: {connection: sales, table: orders}
    measures:
      - {name: total, function: sum, column: revenue}
    result: {kind: scalar, member: total}
""")

        with (
            patch(
                "app.calculations.service.get_calculation",
                new=AsyncMock(
                    return_value={"id": 7, "collection_id": 3, "content": content}
                ),
            ),
            patch(
                "app.calculations.service.get_collection",
                new=AsyncMock(
                    return_value={"id": 3, "cube_names": [], "pipe_ids": [17]}
                ),
            ),
            patch("app.calculations.service.current_organization_id", return_value=41),
            patch(
                "app.calculations.service.validate_aggregate_query",
                new=AsyncMock(),
            ) as validate_source,
        ):
            result = await validate_calculation(7)

        self.assertTrue(result["valid"])
        self.assertEqual("aggregate_query", result["nodes"][0]["type"])
        self.assertEqual(41, validate_source.await_args.kwargs["organization_id"])
        self.assertEqual(
            {17},
            validate_source.await_args.kwargs["allowed_connection_ids"],
        )

    async def test_connection_lookup_is_scoped_to_the_active_organization(self):
        class RecordingDatabase:
            query = ""
            args = ()

            async def fetchrow(self, query, *args):
                self.query = query
                self.args = args
                return None

        database = RecordingDatabase()

        @asynccontextmanager
        async def recording_database():
            yield database

        with patch(
            "app.calculations.aggregate.db_connection",
            recording_database,
        ):
            with self.assertRaises(ResourceNotFoundError):
                await _connection_record("sales", organization_id=41)

        self.assertIn("c.organization_id = $3", database.query)
        self.assertEqual(("sales", "googledrive", 41), database.args)


if __name__ == "__main__":
    unittest.main()
