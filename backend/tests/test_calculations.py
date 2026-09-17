import unittest

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError

from app import calculation_service
from app.calculations.graph import validate_graph
from app.calculations.parser import parse_calculation
from app.errors import (
    InvalidInputError,
    InvalidOperationError,
    ResourceConflictError,
    ResourceNotFoundError,
)
from app.schemas import CalculationCreate

TEST_CALCULATION_CONTENT = """\
version: 1
name: monthly_revenue
nodes:
  - id: amount
    type: value
    value: 100
outputs:
  amount: amount
"""


class CalculationValidationTests(unittest.TestCase):
    def test_example_document_is_a_valid_calculation(self):
        validate_graph(parse_calculation(TEST_CALCULATION_CONTENT))

    def test_create_requires_caller_supplied_content_and_collection(self):
        with self.assertRaises(ValidationError):
            CalculationCreate(name="Monthly revenue")

        self.assertFalse(hasattr(calculation_service, "_starter_content"))

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
    async def test_create_allows_multiple_calculations_in_one_collection(self):
        class RecordingDatabase:
            next_id = 7
            inserts = []

            async def fetchval(self, _query, *args):
                self.inserts.append(args)
                calculation_id = self.next_id
                self.next_id += 1
                return calculation_id

        database = RecordingDatabase()

        @asynccontextmanager
        async def recording_database():
            yield database

        identity = SimpleNamespace(organization_id=41, user_id=5)
        saved = [
            {
                "id": 7,
                "name": "Regional revenue",
                "slug": "regional_revenue",
                "collection_id": 9,
            },
            {
                "id": 8,
                "name": "Customer retention",
                "slug": "customer_retention",
                "collection_id": 9,
            },
        ]

        with (
            patch.object(calculation_service, "db_connection", recording_database),
            patch.object(
                calculation_service,
                "require_organization_write_access",
                return_value=identity,
            ),
            patch.object(
                calculation_service,
                "get_collection",
                return_value={"id": 9},
            ) as get_collection,
            patch.object(
                calculation_service,
                "get_calculation",
                side_effect=saved,
            ),
        ):
            first = await calculation_service.create_calculation(
                collection_id=9,
                name="Regional revenue",
                content=TEST_CALCULATION_CONTENT,
            )
            second = await calculation_service.create_calculation(
                collection_id=9,
                name="Customer retention",
                content=TEST_CALCULATION_CONTENT,
            )

        self.assertEqual([7, 8], [first["id"], second["id"]])
        self.assertEqual([9, 9], [first["collection_id"], second["collection_id"]])
        self.assertEqual(2, get_collection.await_count)
        self.assertEqual("regional_revenue", database.inserts[0][4])
        self.assertEqual("customer_retention", database.inserts[1][4])

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
        self.assertIn("WHERE c.organization_id = $1", database.query)
        self.assertEqual((41,), database.args)

    async def test_list_can_be_scoped_to_one_collection(self):
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
            result = await calculation_service.list_calculations(collection_id=9)

        self.assertEqual([], result)
        self.assertIn("c.collection_id = $2", database.query)
        self.assertEqual((41, 9), database.args)

    async def test_assign_collection_validates_both_resources(self):
        saved = {
            "id": 7,
            "name": "Monthly revenue",
            "collection_id": 9,
            "collection_name": "Finance",
        }

        class RecordingDatabase:
            args = ()

            async def fetchrow(self, _query, *args):
                self.args = args
                return {"id": 7}

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
            patch.object(
                calculation_service,
                "get_collection",
                return_value={"id": 9},
            ) as get_collection,
            patch.object(
                calculation_service,
                "get_calculation",
                return_value=saved,
            ),
        ):
            result = await calculation_service.assign_calculation_collection(
                7,
                collection_id=9,
            )

        self.assertEqual(saved, result)
        get_collection.assert_awaited_once_with(9, include_assets=False)
        self.assertEqual((9, 7, 41), database.args)

    async def test_assign_collection_rejects_move_between_apps(self):
        calculation = {
            "id": 7,
            "name": "Monthly revenue",
            "slug": "monthly_revenue",
            "collection_id": 8,
            "content": "version: 1\nnodes: []\noutputs: {}\n",
        }

        identity = SimpleNamespace(organization_id=41, user_id=5)
        with (
            patch.object(
                calculation_service,
                "require_organization_write_access",
                return_value=identity,
            ),
            patch.object(
                calculation_service,
                "get_collection",
                return_value={"id": 9},
            ),
            patch.object(
                calculation_service,
                "get_calculation",
                return_value=calculation,
            ),
        ):
            with self.assertRaisesRegex(
                InvalidOperationError,
                "cannot be moved between Apps",
            ):
                await calculation_service.assign_calculation_collection(
                    7,
                    collection_id=9,
                )

    async def test_assign_collection_rejects_missing_references_in_destination(self):
        calculation = {
            "id": 7,
            "name": "Revenue forecast",
            "slug": "revenue_forecast",
            "collection_id": None,
            "content": (
                "version: 1\n"
                "nodes:\n"
                "  - id: base\n"
                "    type: calculation_output\n"
                "    calculation: monthly_revenue\n"
                "    output: total\n"
            ),
        }

        class DestinationDatabase:
            async def fetch(self, _query, *_args):
                return [{"slug": "unrelated_calculation"}]

        @asynccontextmanager
        async def destination_database():
            yield DestinationDatabase()

        identity = SimpleNamespace(organization_id=41, user_id=5)
        with (
            patch.object(calculation_service, "db_connection", destination_database),
            patch.object(
                calculation_service,
                "require_organization_write_access",
                return_value=identity,
            ),
            patch.object(
                calculation_service,
                "get_collection",
                return_value={"id": 9},
            ),
            patch.object(
                calculation_service,
                "get_calculation",
                return_value=calculation,
            ),
        ):
            with self.assertRaisesRegex(
                ResourceConflictError,
                "not in the destination App: monthly_revenue",
            ):
                await calculation_service.assign_calculation_collection(
                    7,
                    collection_id=9,
                )

    async def test_update_is_scoped_and_returns_saved_document(self):
        saved = {
            "id": 7,
            "name": "Monthly revenue",
            "slug": "monthly_revenue",
            "collection_id": 9,
            "collection_name": "Finance",
            "collection_slug": "finance",
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
            patch.object(
                calculation_service,
                "get_calculation",
                return_value=saved,
            ),
        ):
            result = await calculation_service.update_calculation(
                7,
                content="version: 1",
                expected_content="version: 0\n",
            )

        self.assertEqual(saved, result)
        self.assertIn("organization_id = $3", database.query)
        self.assertIn("content = $4", database.query)
        self.assertEqual(("version: 1\n", 7, 41, "version: 0\n"), database.args)

    async def test_stale_update_does_not_overwrite_the_saved_calculation(self):
        class StaleDatabase:
            async def fetchrow(self, query, *_args):
                if "UPDATE calculations" in query:
                    return None

                return {"id": 7}

        @asynccontextmanager
        async def stale_database():
            yield StaleDatabase()

        identity = SimpleNamespace(organization_id=41, user_id=5)
        with (
            patch.object(calculation_service, "db_connection", stale_database),
            patch.object(
                calculation_service,
                "require_organization_write_access",
                return_value=identity,
            ),
        ):
            with self.assertRaises(ResourceConflictError):
                await calculation_service.update_calculation(
                    7,
                    content="version: 2\n",
                    expected_content="version: 1\n",
                )

    async def test_update_rejects_a_missing_expected_revision_before_io(self):
        identity = SimpleNamespace(organization_id=41, user_id=5)

        with patch.object(
            calculation_service,
            "require_organization_write_access",
            return_value=identity,
        ):
            with self.assertRaises(InvalidInputError):
                await calculation_service.update_calculation(
                    7,
                    content="version: 2\n",
                    expected_content=None,
                )

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

    async def test_delete_rejects_a_calculation_used_by_another_calculation(self):
        class ReferencedDatabase:
            deleted = False

            async def fetchrow(self, query, *_args):
                if "DELETE FROM calculations" in query:
                    self.deleted = True
                    return {"id": 7, "name": "Base revenue"}

                return {
                    "id": 7,
                    "name": "Base revenue",
                    "slug": "base_revenue",
                    "collection_id": 9,
                }

            async def fetch(self, *_args):
                return [
                    {
                        "id": 8,
                        "name": "Revenue forecast",
                        "content": """\
version: 1
name: revenue_forecast
nodes:
  - id: revenue
    type: calculation_output
    calculation: base_revenue
    output: revenue
    result: {kind: scalar}
outputs: {revenue: revenue}
""",
                    }
                ]

        database = ReferencedDatabase()

        @asynccontextmanager
        async def referenced_database():
            yield database

        identity = SimpleNamespace(organization_id=41, user_id=5)
        with (
            patch.object(calculation_service, "db_connection", referenced_database),
            patch.object(
                calculation_service,
                "require_organization_write_access",
                return_value=identity,
            ),
        ):
            with self.assertRaisesRegex(
                ResourceConflictError,
                "used by: Revenue forecast",
            ):
                await calculation_service.delete_calculation(7)

        self.assertFalse(database.deleted)


if __name__ == "__main__":
    unittest.main()
