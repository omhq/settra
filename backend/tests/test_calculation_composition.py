import unittest

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.calculations.service import execute_calculation, validate_calculation
from app.errors import InvalidInputError


def calculation_row(calculation_id: int, slug: str, content: str) -> dict:
    return {
        "id": calculation_id,
        "name": slug.replace("_", " ").title(),
        "slug": slug,
        "collection_id": 3,
        "content": content,
    }


LEAF_CONTENT = """\
version: 1
name: base_revenue
nodes:
  - id: amount
    type: value
    value: 125
outputs:
  revenue: amount
"""

COMPOSED_CONTENT = """\
version: 1
name: doubled_revenue
nodes:
  - id: revenue
    type: calculation_output
    calculation: base_revenue
    output: revenue
    result: {kind: scalar}
  - id: multiplier
    type: value
    value: 2
  - id: doubled
    type: formula
    inputs: {amount: revenue, multiplier: multiplier}
    expression: amount * multiplier
outputs:
  doubled_revenue: doubled
"""


class CalculationCompositionTests(unittest.IsolatedAsyncioTestCase):
    async def test_calculation_output_can_feed_a_formula(self):
        root = calculation_row(8, "doubled_revenue", COMPOSED_CONTENT)
        leaf = calculation_row(7, "base_revenue", LEAF_CONTENT)

        with (
            patch(
                "app.calculations.service.get_calculation",
                new=AsyncMock(return_value=root),
            ),
            patch(
                "app.calculations.service.get_calculation_in_collection",
                new=AsyncMock(return_value=leaf),
            ) as get_reference,
            patch(
                "app.calculations.service.get_collection",
                new=AsyncMock(return_value={"id": 3, "cube_names": [], "pipe_ids": []}),
            ),
        ):
            result = await execute_calculation(8)

        self.assertEqual(
            250,
            result["outputs"]["doubled_revenue"]["result"]["value"],
        )
        get_reference.assert_awaited_once_with(3, "base_revenue")

    async def test_app_input_is_forwarded_to_a_referenced_calculation(self):
        leaf_content = """\
version: 1
name: regional_revenue
parameters:
  - id: region
    member: sales.region
nodes:
  - id: revenue
    type: cube_query
    query:
      measures: [sales.revenue]
      filters:
        - member: sales.region
          operator: equals
          parameter: region
    result: {kind: scalar, member: sales.revenue}
outputs:
  revenue: revenue
"""
        root_content = """\
version: 1
name: regional_summary
parameters:
  - id: selected_region
    member: sales.region
nodes:
  - id: regional_revenue
    type: calculation_output
    calculation: regional_revenue
    output: revenue
    arguments: {region: selected_region}
    result: {kind: scalar}
outputs:
  revenue: regional_revenue
"""
        root = calculation_row(8, "regional_summary", root_content)
        leaf = calculation_row(7, "regional_revenue", leaf_content)
        catalog = SimpleNamespace(
            compiled_meta=AsyncMock(
                return_value={
                    "cubes": [
                        {
                            "name": "sales",
                            "dimensions": [
                                {
                                    "name": "sales.region",
                                    "title": "Region",
                                    "type": "string",
                                }
                            ],
                        }
                    ]
                }
            )
        )
        cube_response = {
            "data": [{"sales.revenue": "125"}],
            "query": {},
            "cube": {},
        }

        with (
            patch(
                "app.calculations.service.get_calculation",
                new=AsyncMock(return_value=root),
            ),
            patch(
                "app.calculations.service.get_calculation_in_collection",
                new=AsyncMock(return_value=leaf),
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
                "app.calculations.executor.execute_cube_query_payload",
                new=AsyncMock(return_value=cube_response),
            ) as execute_cube,
        ):
            result = await execute_calculation(
                8,
                parameters={"selected_region": "North"},
            )

        self.assertEqual(125, result["outputs"]["revenue"]["result"]["value"])
        sent_filter = execute_cube.await_args.args[0]["query"]["filters"][0]
        self.assertEqual(["North"], sent_filter["values"])
        self.assertNotIn("parameter", sent_filter)

    async def test_validation_rejects_cross_calculation_cycles(self):
        first_content = """\
version: 1
name: first
nodes:
  - id: second_value
    type: calculation_output
    calculation: second
    output: value
    result: {kind: scalar}
outputs: {value: second_value}
"""
        second_content = """\
version: 1
name: second
nodes:
  - id: first_value
    type: calculation_output
    calculation: first
    output: value
    result: {kind: scalar}
outputs: {value: first_value}
"""
        calculations = {
            "first": calculation_row(7, "first", first_content),
            "second": calculation_row(8, "second", second_content),
        }

        async def get_reference(_collection_id, slug):
            return calculations[slug]

        with (
            patch(
                "app.calculations.service.get_calculation",
                new=AsyncMock(return_value=calculations["first"]),
            ),
            patch(
                "app.calculations.service.get_calculation_in_collection",
                new=AsyncMock(side_effect=get_reference),
            ),
            patch(
                "app.calculations.service.get_collection",
                new=AsyncMock(return_value={"id": 3, "cube_names": [], "pipe_ids": []}),
            ),
        ):
            with self.assertRaisesRegex(
                InvalidInputError,
                "dependency cycle: first -> second -> first",
            ):
                await validate_calculation(7)


if __name__ == "__main__":
    unittest.main()
