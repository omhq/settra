import unittest

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.calculations.executor import execute_definition
from app.calculations.parameters import (
    bind_cube_query_parameters,
    resolve_calculation_parameters,
    validate_parameter_values,
)
from app.calculations.parser import parse_calculation
from app.calculations.service import (
    calculation_parameter_options,
    execute_calculation,
    validate_calculation,
)
from app.errors import InvalidInputError


def parameter_content(
    *,
    parameter_member: str = "sales.region",
    filter_member: str = "sales.region",
    operator: str = "equals",
    parameter_filter_extra: str = "",
) -> str:
    return f"""\
version: 1
name: regional_revenue
parameters:
  - id: region
    member: {parameter_member}
nodes:
  - id: revenue
    type: cube_query
    query:
      measures: [sales.revenue]
      filters:
        - member: {filter_member}
          operator: {operator}
          parameter: region
{parameter_filter_extra}    result:
      kind: scalar
      member: sales.revenue
outputs:
  revenue: revenue
"""


def cube_meta(dimension_type: str = "string") -> dict:
    return {
        "cubes": [
            {
                "name": "sales",
                "dimensions": [
                    {
                        "name": "sales.region",
                        "title": "Sales Region",
                        "type": dimension_type,
                    }
                ],
            }
        ]
    }


class CalculationParameterContractTests(unittest.TestCase):
    def test_parameter_ids_must_be_unique(self):
        content = parameter_content().replace(
            "nodes:\n",
            "  - id: region\n    member: sales.region\nnodes:\n",
            1,
        )

        with self.assertRaisesRegex(InvalidInputError, "parameter ids must be unique"):
            parse_calculation(content)

    def test_cube_metadata_supplies_parameter_type_and_input(self):
        definition = parse_calculation(parameter_content())

        resolved = resolve_calculation_parameters(definition, cube_meta())

        self.assertEqual(
            {
                "id": "region",
                "member": "sales.region",
                "title": "Sales Region",
                "type": "string",
                "input": "select",
                "cardinality": "one_or_more",
                "required": True,
                "operators": ["equals"],
                "options_available": True,
            },
            resolved["region"].descriptor(),
        )

    def test_rejects_binding_a_parameter_to_another_dimension(self):
        definition = parse_calculation(parameter_content(filter_member="sales.country"))

        with self.assertRaisesRegex(InvalidInputError, "binds it to 'sales.country'"):
            resolve_calculation_parameters(definition, cube_meta())

    def test_rejects_an_operator_that_does_not_match_the_cube_type(self):
        definition = parse_calculation(parameter_content(operator="contains"))

        with self.assertRaisesRegex(InvalidInputError, "not valid for number"):
            resolve_calculation_parameters(definition, cube_meta("number"))

    def test_rejects_literal_values_on_a_parameter_filter(self):
        definition = parse_calculation(
            parameter_content(parameter_filter_extra="          values: [North]\n")
        )

        with self.assertRaisesRegex(InvalidInputError, "cannot also set values"):
            resolve_calculation_parameters(definition, cube_meta())

    def test_binds_nested_filters_without_forwarding_the_parameter_key(self):
        definition = parse_calculation("""\
version: 1
name: regional_revenue
parameters:
  - {id: region, member: sales.region}
nodes:
  - id: revenue
    type: cube_query
    query:
      measures: [sales.revenue]
      filters:
        - or:
            - {member: sales.region, operator: equals, parameter: region}
            - {member: sales.status, operator: equals, values: [pending]}
    result: {kind: scalar, member: sales.revenue}
outputs:
  revenue: revenue
""")
        resolved = resolve_calculation_parameters(definition, cube_meta())

        query = bind_cube_query_parameters(
            definition.nodes[0].query,
            resolved,
            {"region": ["North", "West"]},
        )

        bound_filter = query["filters"][0]["or"][0]
        self.assertEqual(["North", "West"], bound_filter["values"])
        self.assertNotIn("parameter", bound_filter)
        self.assertIn("parameter", definition.nodes[0].query["filters"][0]["or"][0])

    def test_parameter_values_are_typed_and_complete_before_execution(self):
        definition = parse_calculation(parameter_content())
        resolved = resolve_calculation_parameters(definition, cube_meta())

        with self.assertRaisesRegex(InvalidInputError, "requires.*region"):
            validate_parameter_values(definition, resolved, {})
        with self.assertRaisesRegex(InvalidInputError, "requires string"):
            validate_parameter_values(definition, resolved, {"region": 7})
        with self.assertRaisesRegex(InvalidInputError, "unknown.*typo"):
            validate_parameter_values(
                definition,
                resolved,
                {"region": "North", "typo": "value"},
            )

    def test_number_boolean_and_time_values_are_serialized_for_cube(self):
        cases = (
            ("number", "gte", 25.5, ["25.5"]),
            ("boolean", "equals", True, ["true"]),
            (
                "time",
                "inDateRange",
                ["2026-01-01", "2026-01-31"],
                ["2026-01-01", "2026-01-31"],
            ),
        )

        for dimension_type, operator, value, expected in cases:
            with self.subTest(dimension_type=dimension_type):
                definition = parse_calculation(parameter_content(operator=operator))
                resolved = resolve_calculation_parameters(
                    definition,
                    cube_meta(dimension_type),
                )
                validate_parameter_values(definition, resolved, {"region": value})
                query = bind_cube_query_parameters(
                    definition.nodes[0].query,
                    resolved,
                    {"region": value},
                )
                self.assertEqual(expected, query["filters"][0]["values"])


class CalculationParameterExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_executor_sends_only_cube_filter_values(self):
        definition = parse_calculation(parameter_content())
        resolved = resolve_calculation_parameters(definition, cube_meta())
        cube_response = {
            "ok": True,
            "query": {},
            "cube": {},
            "data": [{"sales.revenue": "125.5"}],
        }

        with patch(
            "app.calculations.executor.execute_cube_query_payload",
            new=AsyncMock(return_value=cube_response),
        ) as execute_cube:
            result = await execute_definition(
                definition,
                allowed_cube_names={"sales"},
                parameter_values={"region": "North"},
                resolved_parameters=resolved,
            )

        sent_filter = execute_cube.await_args.args[0]["query"]["filters"][0]
        self.assertEqual(["North"], sent_filter["values"])
        self.assertNotIn("parameter", sent_filter)
        self.assertEqual(
            125.5,
            result["outputs"]["revenue"]["result"]["value"],
        )

    async def test_service_validates_parameters_before_running_any_node(self):
        content = parameter_content()
        catalog = SimpleNamespace(compiled_meta=AsyncMock(return_value=cube_meta()))

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
            patch(
                "app.calculations.service.semantic_catalog_service",
                return_value=catalog,
            ),
            patch(
                "app.calculations.service.execute_definition",
                new=AsyncMock(),
            ) as execute,
        ):
            with self.assertRaisesRegex(InvalidInputError, "requires.*region"):
                await execute_calculation(7)

        execute.assert_not_awaited()

    async def test_validation_returns_the_cube_derived_parameter_contract(self):
        content = parameter_content()
        catalog = SimpleNamespace(compiled_meta=AsyncMock(return_value=cube_meta()))

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
            patch(
                "app.calculations.service.semantic_catalog_service",
                return_value=catalog,
            ),
        ):
            result = await validate_calculation(7)

        self.assertEqual("string", result["parameters"][0]["type"])
        self.assertEqual("select", result["parameters"][0]["input"])

    async def test_options_are_distinct_values_queried_from_cube(self):
        content = parameter_content()
        catalog = SimpleNamespace(compiled_meta=AsyncMock(return_value=cube_meta()))
        cube_response = {
            "data": [
                {"sales.region": "North"},
                {"sales.region": "South"},
            ]
        }

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
            patch(
                "app.calculations.service.semantic_catalog_service",
                return_value=catalog,
            ),
            patch(
                "app.calculations.service.execute_cube_query_payload",
                new=AsyncMock(return_value=cube_response),
            ) as execute_cube,
        ):
            result = await calculation_parameter_options(
                7,
                "region",
                search="No",
            )

        query = execute_cube.await_args.args[0]["query"]
        self.assertEqual(["sales.region"], query["dimensions"])
        self.assertEqual(["No"], query["filters"][0]["values"])
        self.assertEqual(101, query["limit"])
        self.assertEqual(["North", "South"], result["options"])
        self.assertFalse(result["has_more"])


if __name__ == "__main__":
    unittest.main()
