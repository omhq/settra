import unittest

from decimal import Decimal
from unittest.mock import AsyncMock, patch

from app.calculations.executor import execute_definition
from app.calculations.formula import evaluate_formula
from app.calculations.graph import dependency_order, validate_graph
from app.calculations.parser import parse_calculation
from app.calculations.service import execute_calculation, validate_calculation
from app.errors import InvalidInputError, InvalidOperationError


def calculation_content(nodes: str, output: str) -> str:
    return f"""\
version: 1
name: test_calculation
nodes:
{nodes}
outputs:
  result: {output}
"""


class CalculationDefinitionTests(unittest.TestCase):
    def test_parses_and_plans_formula_dependencies(self):
        definition = parse_calculation(
            calculation_content(
                """\
  - id: base
    type: value
    value: 100
  - id: multiplier
    type: value
    value: 1.2
  - id: forecast
    type: formula
    inputs:
      amount: base
      rate: multiplier
    expression: amount * rate
""",
                "forecast",
            )
        )

        validate_graph(definition)

        self.assertEqual(
            ["base", "multiplier", "forecast"],
            dependency_order(definition, "forecast"),
        )

    def test_rejects_an_output_that_references_a_missing_node(self):
        definition = parse_calculation(
            calculation_content(
                """\
  - id: amount
    type: value
    value: 100
""",
                "missing",
            )
        )

        with self.assertRaisesRegex(
            InvalidInputError,
            "result -> missing",
        ):
            validate_graph(definition)

    def test_rejects_dependency_cycles(self):
        definition = parse_calculation(
            calculation_content(
                """\
  - id: first
    type: formula
    inputs: {value: second}
    expression: value + 1
  - id: second
    type: formula
    inputs: {value: first}
    expression: value + 1
""",
                "first",
            )
        )

        with self.assertRaises(InvalidInputError) as raised:
            validate_graph(definition)

        self.assertIn("dependency cycle", raised.exception.message)

    def test_rejects_executable_python_in_formula(self):
        definition = parse_calculation(
            calculation_content(
                """\
  - id: base
    type: value
    value: 100
  - id: unsafe
    type: formula
    inputs: {value: base}
    expression: __import__('os').system('whoami')
""",
                "unsafe",
            )
        )

        with self.assertRaises(InvalidInputError) as raised:
            validate_graph(definition)

        self.assertIn("may only contain", raised.exception.message)

    def test_rejects_table_as_formula_input(self):
        definition = parse_calculation(
            calculation_content(
                """\
  - id: rows
    type: cube_query
    query:
      dimensions: [sales.region]
  - id: total
    type: formula
    inputs: {value: rows}
    expression: value + 1
""",
                "total",
            )
        )

        with self.assertRaises(InvalidInputError) as raised:
            validate_graph(definition)

        self.assertIn("requires scalar inputs", raised.exception.message)

    def test_value_nodes_require_yaml_numbers(self):
        with self.assertRaises(InvalidInputError) as raised:
            parse_calculation(
                calculation_content(
                    """\
  - id: amount
    type: value
    value: "100"
""",
                    "amount",
                )
            )

        self.assertIn("value must be a YAML number", raised.exception.message)


class FormulaEvaluationTests(unittest.TestCase):
    def test_evaluates_decimal_arithmetic(self):
        result = evaluate_formula(
            "(base * multiplier) - discount",
            {
                "base": Decimal("100.10"),
                "multiplier": Decimal("1.2"),
                "discount": Decimal("0.12"),
            },
        )

        self.assertEqual(Decimal("120.000"), result)


class CalculationExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_executes_multiple_named_outputs_in_one_dependency_plan(self):
        definition = parse_calculation("""\
version: 1
name: revenue_forecast
nodes:
  - id: revenue
    type: value
    value: 100
  - id: multiplier
    type: value
    value: 1.2
  - id: forecast
    type: formula
    inputs: {base: revenue, rate: multiplier}
    expression: base * rate
outputs:
  actual_revenue: revenue
  forecast_revenue: forecast
""")

        result = await execute_definition(
            definition,
            allowed_cube_names=set(),
        )

        self.assertIsNone(result["target_node_id"])
        self.assertEqual(
            ["revenue", "multiplier", "forecast"],
            result["execution_order"],
        )
        self.assertEqual(
            {
                "node_id": "revenue",
                "result": {"kind": "scalar", "value": 100},
            },
            result["outputs"]["actual_revenue"],
        )
        self.assertEqual(
            120,
            result["outputs"]["forecast_revenue"]["result"]["value"],
        )
        self.assertNotIn("result", result)

    async def test_executes_only_the_requested_dependency_closure(self):
        definition = parse_calculation(
            calculation_content(
                """\
  - id: base
    type: value
    value: 80
  - id: multiplier
    type: value
    value: 1.5
  - id: forecast
    type: formula
    inputs: {amount: base, rate: multiplier}
    expression: amount * rate
  - id: unused_query
    type: cube_query
    query:
      measures: [sales.row_count]
    result:
      kind: scalar
      member: sales.row_count
""",
                "forecast",
            )
        )
        validate_graph(definition)

        with patch(
            "app.calculations.executor.execute_cube_query_payload",
            new=AsyncMock(),
        ) as execute_cube:
            result = await execute_definition(
                definition,
                allowed_cube_names={"sales"},
                target_node_id="forecast",
            )

        self.assertEqual(120, result["result"]["value"])
        self.assertEqual(["base", "multiplier", "forecast"], result["execution_order"])
        execute_cube.assert_not_awaited()

    async def test_executes_cube_scalar_then_formula(self):
        definition = parse_calculation(
            calculation_content(
                """\
  - id: revenue
    type: cube_query
    query:
      measures: [sales.revenue]
    result:
      kind: scalar
      member: sales.revenue
  - id: multiplier
    type: value
    value: 1.2
  - id: forecast
    type: formula
    inputs: {base: revenue, rate: multiplier}
    expression: base * rate
""",
                "forecast",
            )
        )
        validate_graph(definition)
        cube_response = {
            "ok": True,
            "query": {"measures": ["sales.revenue"], "limit": 2},
            "cube": {
                "data": [{"sales.revenue": "125.5"}],
                "annotation": {
                    "measures": {"sales.revenue": {"type": "number"}},
                },
            },
            "data": [{"sales.revenue": "125.5"}],
        }

        with patch(
            "app.calculations.executor.execute_cube_query_payload",
            new=AsyncMock(return_value=cube_response),
        ) as execute_cube:
            result = await execute_definition(
                definition,
                allowed_cube_names={"sales"},
            )

        self.assertEqual(
            150.6,
            result["outputs"]["result"]["result"]["value"],
        )
        call = execute_cube.await_args
        self.assertEqual(2, call.args[0]["query"]["limit"])
        self.assertEqual({"sales"}, call.kwargs["allowed_names"])

    async def test_table_results_are_bounded_with_a_sentinel_row(self):
        definition = parse_calculation(
            calculation_content(
                """\
  - id: regions
    type: cube_query
    query:
      dimensions: [sales.region]
      limit: 2
""",
                "regions",
            )
        )
        validate_graph(definition)
        cube_response = {
            "ok": True,
            "query": {"dimensions": ["sales.region"], "limit": 3},
            "cube": {},
            "data": [
                {"sales.region": "North"},
                {"sales.region": "South"},
                {"sales.region": "West"},
            ],
        }

        with patch(
            "app.calculations.executor.execute_cube_query_payload",
            new=AsyncMock(return_value=cube_response),
        ) as execute_cube:
            result = await execute_definition(
                definition,
                allowed_cube_names={"sales"},
            )

        table = result["outputs"]["result"]["result"]
        self.assertEqual(2, table["row_count"])
        self.assertTrue(table["has_more"])
        self.assertNotIn("rows", result["nodes"][0]["result"])
        self.assertEqual(3, execute_cube.await_args.args[0]["query"]["limit"])


class CalculationServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_unassigned_calculation_cannot_validate_or_execute(self):
        content = calculation_content(
            """\
  - id: amount
    type: value
    value: 100
""",
            "amount",
        )

        with patch(
            "app.calculations.service.get_calculation",
            new=AsyncMock(
                return_value={"id": 7, "collection_id": None, "content": content}
            ),
        ):
            with self.assertRaisesRegex(
                InvalidOperationError,
                "Assign this calculation to a collection",
            ):
                await validate_calculation(7)

    async def test_validation_accepts_unsaved_content_and_reports_plan(self):
        content = calculation_content(
            """\
  - id: revenue
    type: cube_query
    query:
      measures: [sales.revenue]
    result:
      kind: scalar
      member: sales.revenue
""",
            "revenue",
        )

        with (
            patch(
                "app.calculations.service.get_calculation",
                new=AsyncMock(
                    return_value={
                        "id": 7,
                        "collection_id": 3,
                        "content": "saved: draft\n",
                    }
                ),
            ),
            patch(
                "app.calculations.service.get_collection",
                new=AsyncMock(
                    return_value={"id": 3, "cube_names": ["sales"], "pipe_ids": []}
                ),
            ),
        ):
            result = await validate_calculation(7, content=content)

        self.assertTrue(result["valid"])
        self.assertEqual({"result": "revenue"}, result["outputs"])
        self.assertEqual(["revenue"], result["execution_order"])
        self.assertEqual("cube_query", result["nodes"][0]["type"])
        self.assertEqual(["result"], result["nodes"][0]["used_by_outputs"])

    async def test_target_execution_ignores_disconnected_cube_nodes(self):
        content = calculation_content(
            """\
  - id: preview
    type: value
    value: 42
  - id: unfinished
    type: cube_query
    query:
      measures: [not_configured.revenue]
    result:
      kind: scalar
      member: not_configured.revenue
""",
            "preview",
        )

        with (
            patch(
                "app.calculations.service.get_calculation",
                new=AsyncMock(
                    return_value={"id": 7, "collection_id": 3, "content": content}
                ),
            ),
            patch(
                "app.calculations.service.get_collection",
                new=AsyncMock(return_value={"id": 3, "cube_names": [], "pipe_ids": []}),
            ),
        ):
            result = await execute_calculation(7, target_node_id="preview")

        self.assertEqual(42, result["result"]["value"])

    async def test_validation_rejects_raw_sql(self):
        content = calculation_content(
            """\
  - id: unsafe
    type: cube_query
    query:
      sql: SELECT * FROM secrets
      measures: [sales.revenue]
""",
            "unsafe",
        )

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
                    return_value={"id": 3, "cube_names": ["sales"], "pipe_ids": []}
                ),
            ),
        ):
            with self.assertRaises(InvalidInputError) as raised:
                await validate_calculation(7)

        self.assertIn("Raw SQL is not supported", raised.exception.message)

    async def test_validation_caps_query_node_count(self):
        nodes = "\n".join(f"""\
  - id: query_{index}
    type: cube_query
    query:
      measures: [sales.revenue]""" for index in range(11))
        content = calculation_content(nodes + "\n", "query_0")

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
                    return_value={"id": 3, "cube_names": ["sales"], "pipe_ids": []}
                ),
            ),
        ):
            with self.assertRaises(InvalidInputError) as raised:
                await validate_calculation(7)

        self.assertIn("at most 10 query nodes", raised.exception.message)


if __name__ == "__main__":
    unittest.main()
