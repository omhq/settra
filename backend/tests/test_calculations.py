import unittest

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import patch

import yaml

from app import calculation_service
from app.errors import InvalidInputError, ResourceNotFoundError


class CalculationValidationTests(unittest.TestCase):
    def test_starter_document_is_valid_mapping(self):
        content = calculation_service._starter_content("monthly_revenue")
        parsed = yaml.safe_load(content)

        self.assertEqual(1, parsed["version"])
        self.assertEqual("monthly_revenue", parsed["name"])
        self.assertEqual("source", parsed["output"])
        self.assertEqual("source", parsed["nodes"][0]["id"])

    def test_yaml_must_be_a_mapping(self):
        with self.assertRaises(InvalidInputError) as raised:
            calculation_service._validated_content("- one\n- two\n")

        self.assertEqual(
            "Calculation YAML must contain a mapping",
            raised.exception.message,
        )

    def test_invalid_yaml_is_rejected(self):
        with self.assertRaises(InvalidInputError) as raised:
            calculation_service._validated_content("nodes: [\n")

        self.assertIn("Invalid calculation YAML", raised.exception.message)


class CalculationServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_is_scoped_to_active_organization(self):
        class RecordingDatabase:
            query = ""
            args = ()

            async def fetch(self, query, *args):
                self.query = query
                self.args = args
                return []

        database = RecordingDatabase()

        @asynccontextmanager
        async def recording_database():
            yield database

        with (
            patch.object(calculation_service, "db_connection", recording_database),
            patch.object(
                calculation_service,
                "current_organization_id",
                return_value=41,
            ),
        ):
            result = await calculation_service.list_calculations()

        self.assertEqual([], result)
        self.assertIn("WHERE organization_id = $1", database.query)
        self.assertEqual((41,), database.args)

    async def test_update_is_scoped_and_returns_saved_document(self):
        saved = {
            "id": 7,
            "name": "Monthly revenue",
            "slug": "monthly_revenue",
            "content": "version: 1\n",
            "created_at": "2026-09-13",
            "updated_at": "2026-09-13",
        }

        class RecordingDatabase:
            query = ""
            args = ()

            async def fetchrow(self, query, *args):
                self.query = query
                self.args = args
                return saved

        database = RecordingDatabase()

        @asynccontextmanager
        async def recording_database():
            yield database

        identity = SimpleNamespace(organization_id=41, user_id=5)
        with (
            patch.object(calculation_service, "db_connection", recording_database),
            patch.object(
                calculation_service,
                "require_organization_write_access",
                return_value=identity,
            ),
        ):
            result = await calculation_service.update_calculation(
                7,
                content="version: 1",
            )

        self.assertEqual(saved, result)
        self.assertIn("organization_id = $3", database.query)
        self.assertEqual(("version: 1\n", 7, 41), database.args)

    async def test_delete_missing_calculation_returns_not_found(self):
        class EmptyDatabase:
            async def fetchrow(self, *_args):
                return None

        @asynccontextmanager
        async def empty_database():
            yield EmptyDatabase()

        identity = SimpleNamespace(organization_id=41, user_id=5)
        with (
            patch.object(calculation_service, "db_connection", empty_database),
            patch.object(
                calculation_service,
                "require_organization_write_access",
                return_value=identity,
            ),
        ):
            with self.assertRaises(ResourceNotFoundError):
                await calculation_service.delete_calculation(999)


if __name__ == "__main__":
    unittest.main()
