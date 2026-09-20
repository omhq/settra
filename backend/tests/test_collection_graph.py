import json
import unittest
from unittest.mock import AsyncMock, patch

from app import collection_graph_service as graph_service
from app.calculations.executor import execute_definition
from app.calculations.parser import parse_calculation
from app.collection_graph_service import (
    _initial_graph_content,
    _validated_layout,
)
from app.errors import InvalidInputError

COLLECTION = {
    "id": 9,
    "name": "Finance",
    "slug": "finance",
    "description": "Finance planning",
}


class CollectionGraphDraftTests(unittest.TestCase):
    def test_empty_app_starts_with_an_empty_valid_graph(self):
        content, warnings = _initial_graph_content(COLLECTION, [])
        definition = parse_calculation(content)

        self.assertEqual([], definition.nodes)
        self.assertEqual({}, definition.outputs)
        self.assertEqual([], warnings)

    def test_one_existing_calculation_is_preserved_exactly(self):
        content = """\
version: 1
name: revenue
nodes:
  - id: amount
    type: value
    value: 100
outputs: {amount: amount}
"""
        projected, warnings = _initial_graph_content(
            COLLECTION,
            [{"name": "Revenue", "slug": "revenue", "content": content}],
        )

        self.assertEqual(content, projected)
        self.assertEqual([], warnings)

    def test_layout_is_bounded_and_normalized(self):
        encoded = _validated_layout(
            {
                "version": 1,
                "nodes": {"amount": {"x": 1.234, "y": -5}},
                "viewport": {"x": -12.345, "y": 67.891, "zoom": 0.67891},
            }
        )

        self.assertEqual(
            {
                "version": 1,
                "nodes": {"amount": {"x": 1.23, "y": -5.0}},
                "viewport": {"x": -12.35, "y": 67.89, "zoom": 0.6789},
            },
            json.loads(encoded),
        )

        with self.assertRaises(InvalidInputError):
            _validated_layout(
                {"version": 1, "nodes": {"amount": {"x": float("inf"), "y": 0}}}
            )

        with self.assertRaises(InvalidInputError):
            _validated_layout(
                {
                    "version": 1,
                    "nodes": {},
                    "viewport": {"x": 0, "y": 0, "zoom": 0},
                }
            )


class CollectionGraphImportTests(unittest.IsolatedAsyncioTestCase):
    async def test_multiple_calculations_become_one_executable_graph(self):
        base = """\
version: 1
name: base_revenue
nodes:
  - id: amount
    type: value
    value: 100
outputs: {revenue: amount}
"""
        forecast = """\
version: 1
name: forecast
nodes:
  - id: base
    type: calculation_output
    calculation: base_revenue
    output: revenue
    result: {kind: scalar}
  - id: multiplier
    type: value
    value: 1.2
  - id: result
    type: formula
    inputs: {amount: base, rate: multiplier}
    expression: amount * rate
outputs: {forecast: result}
"""

        content, warnings = _initial_graph_content(
            COLLECTION,
            [
                {"name": "Base revenue", "slug": "base_revenue", "content": base},
                {"name": "Forecast", "slug": "forecast", "content": forecast},
            ],
        )
        definition = parse_calculation(content)

        self.assertEqual([], warnings)
        self.assertNotIn(
            "calculation_output",
            {node.type for node in definition.nodes},
        )
        self.assertEqual(
            {"base_revenue__revenue", "forecast__forecast"},
            set(definition.outputs),
        )
        self.assertEqual(3, len(definition.nodes))
        formula = next(
            node for node in definition.nodes if node.id == "forecast__result"
        )
        self.assertEqual(
            definition.outputs["base_revenue__revenue"],
            formula.inputs["amount"],
        )

        result = await execute_definition(definition, allowed_cube_names=set())

        self.assertEqual(
            100,
            result["outputs"]["base_revenue__revenue"]["result"]["value"],
        )
        self.assertEqual(
            120,
            result["outputs"]["forecast__forecast"]["result"]["value"],
        )

    async def test_dependency_impact_prefers_a_saved_graph_over_legacy_drafts(self):
        class Database:
            async def fetchrow(self, _query, *_args):
                return {"content": "version: 1\nnodes: []\noutputs: {}\n"}

        class Context:
            async def __aenter__(self):
                return Database()

            async def __aexit__(self, *_args):
                return None

        legacy = AsyncMock(return_value=[{"id": 1}])
        with (
            patch.object(graph_service, "db_connection", return_value=Context()),
            patch.object(graph_service, "current_organization_id", return_value=4),
            patch.object(graph_service, "list_calculation_documents", legacy),
        ):
            documents = await graph_service.list_effective_graph_documents(9)

        self.assertEqual("app_graph", documents[0]["slug"])
        self.assertEqual(-9, documents[0]["id"])
        legacy.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
