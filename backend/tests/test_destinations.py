import unittest

from contextlib import asynccontextmanager
from unittest.mock import patch

from app.destinations import (
    BUILT_IN_DESTINATION_SLUG,
    connection_destination,
    runtime_from_connection,
)
from app.routers import destinations


class DestinationRuntimeTests(unittest.TestCase):
    def test_pipe_destination_is_independent_from_source_slug(self):
        connection = {
            "id": 8,
            "slug": "source_orders",
            "destination_id": 3,
            "destination_schema": "warehouse_orders",
            "destination_name": "Built-in PostgreSQL",
            "destination_slug": BUILT_IN_DESTINATION_SLUG,
            "destination_type": "postgres",
            "destination_configuration": {"mode": "environment"},
            "destination_is_builtin": True,
            "destination_is_default": True,
        }

        runtime = runtime_from_connection(connection)
        public = connection_destination(connection)

        self.assertEqual("source_orders", connection["slug"])
        self.assertEqual("warehouse_orders", runtime.schema)
        self.assertEqual("warehouse_orders", public["schema"])
        self.assertEqual(3, public["id"])
        self.assertNotIn("password", str(public).lower())


class DestinationRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_lists_the_registered_built_in_destination(self):
        class DestinationDatabase:
            async def fetch(self, query):
                self.query = query
                return [
                    {
                        "id": 1,
                        "name": "Built-in PostgreSQL",
                        "slug": BUILT_IN_DESTINATION_SLUG,
                        "type": "postgres",
                        "configuration": {"mode": "environment"},
                        "is_builtin": True,
                        "is_default": True,
                    }
                ]

        @asynccontextmanager
        async def destination_database():
            yield DestinationDatabase()

        with patch.object(destinations, "db_connection", destination_database):
            result = await destinations.list_destinations()

        self.assertEqual(1, len(result))
        self.assertEqual(BUILT_IN_DESTINATION_SLUG, result[0]["slug"])
        self.assertTrue(result[0]["is_default"])
        self.assertFalse(result[0]["configurable"])
        self.assertIn("location", result[0])


if __name__ == "__main__":
    unittest.main()
