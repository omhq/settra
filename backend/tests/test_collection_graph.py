import json
import unittest
from unittest.mock import patch

from app import collection_graph_service as graph_service
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
        content = _initial_graph_content(COLLECTION)
        definition = parse_calculation(content)

        self.assertEqual([], definition.nodes)
        self.assertEqual({}, definition.outputs)

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


class CollectionGraphDocumentTests(unittest.IsolatedAsyncioTestCase):
    async def test_dependency_impact_reads_the_saved_graph(self):
        class Database:
            async def fetchrow(self, _query, *_args):
                return {"content": "version: 1\nnodes: []\noutputs: {}\n"}

        class Context:
            async def __aenter__(self):
                return Database()

            async def __aexit__(self, *_args):
                return None

        with (
            patch.object(graph_service, "db_connection", return_value=Context()),
            patch.object(graph_service, "current_organization_id", return_value=4),
        ):
            documents = await graph_service.list_effective_graph_documents(9)

        self.assertEqual("app_graph", documents[0]["slug"])
        self.assertEqual(-9, documents[0]["id"])


if __name__ == "__main__":
    unittest.main()
