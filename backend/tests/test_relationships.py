import copy
import unittest

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

from app.relationship_service import validate_relationship_data
from app.semantic.relationships import (
    build_relationship_catalog,
    relationship_join_sql,
    relationship_members,
    test_relationship_catalog as run_relationship_tests,
)
from app.errors import InvalidInputError


def _cube(
    name: str,
    *,
    primary_key: str,
    connection_id: int = 1,
    joins: list[dict] | None = None,
) -> dict:
    return {
        "path": f"overlays/generated/organizations/1/{name}.yaml",
        "source_type": "generated_overlay",
        "definition": {
            "name": name,
            "sql_table": f'"{name}"."rows"',
            "meta": {"settra": {"connection_id": connection_id}},
            "dimensions": [
                {
                    "name": primary_key,
                    "sql": f'"{primary_key}"',
                    "type": "string",
                    "primary_key": True,
                }
            ],
            **({"joins": joins} if joins is not None else {}),
        },
    }


def _renamed_definitions(sql="{CUBE.account_id} = {accounts.id}"):
    definitions = {
        "accounts": _cube("accounts", primary_key="id"),
        "subscriptions": _cube(
            "subscriptions",
            primary_key="subscription_id",
            connection_id=2,
            joins=[{"name": "accounts", "sql": sql, "relationship": "many_to_one"}],
        ),
    }
    definitions["accounts"]["definition"]["dimensions"][0]["sql"] = '"CRM Account ID"'
    definitions["subscriptions"]["definition"]["dimensions"].append(
        {
            "name": "account_id",
            "sql": '{CUBE}."billing_account_identifier"',
            "type": "string",
        }
    )
    return definitions


def _catalog(definitions):
    return build_relationship_catalog(
        allowed_names=set(definitions),
        definitions=definitions,
        compiled_names=set(definitions),
    )


class RelationshipCatalogTests(unittest.TestCase):
    def test_semantic_references_resolve_renamed_physical_keys(self):
        catalog = _catalog(_renamed_definitions())
        relationship = catalog["relationships"][0]
        self.assertTrue(catalog["valid"])
        self.assertEqual("account_id", relationship["source_member"])
        self.assertEqual("id", relationship["target_member"])
        self.assertEqual("billing_account_identifier", relationship["source_column"])
        self.assertEqual("CRM Account ID", relationship["target_column"])

    def test_literal_columns_resolve_to_semantic_names(self):
        catalog = _catalog(
            _renamed_definitions(
                '{CUBE}.billing_account_identifier = {accounts}."CRM Account ID"'
            )
        )
        relationship = catalog["relationships"][0]
        self.assertTrue(catalog["valid"])
        self.assertEqual("account_id", relationship["source_member"])
        self.assertEqual("id", relationship["target_member"])

    def test_mismatched_literal_join_is_invalid_and_preserves_repair_hint(self):
        catalog = _catalog(_renamed_definitions("{CUBE}.account_id = {accounts}.id"))
        relationship = catalog["relationships"][0]
        self.assertFalse(catalog["valid"])
        self.assertEqual("account_id", relationship["source_member"])
        self.assertEqual("id", relationship["target_member"])
        self.assertEqual(
            ["JOIN_COLUMN_MEMBER_MISMATCH", "JOIN_COLUMN_MEMBER_MISMATCH"],
            [issue["code"] for issue in relationship["issues"]],
        )

    def test_literal_join_does_not_guess_between_dimensions(self):
        definitions = _renamed_definitions(
            "{CUBE}.billing_account_identifier = {accounts.id}"
        )
        definitions["subscriptions"]["definition"]["dimensions"].append(
            {"name": "account_alias", "sql": "{CUBE.account_id}", "type": "string"}
        )
        catalog = _catalog(definitions)
        self.assertFalse(catalog["valid"])
        self.assertIn(
            "AMBIGUOUS_JOIN_COLUMN",
            [issue["code"] for issue in catalog["relationships"][0]["issues"]],
        )
        definitions["subscriptions"]["definition"]["joins"][0][
            "sql"
        ] = "{CUBE.account_alias} = {accounts.id}"
        relationship = _catalog(definitions)["relationships"][0]
        self.assertTrue(relationship["valid"])
        self.assertEqual("account_alias", relationship["source_member"])
        self.assertEqual("billing_account_identifier", relationship["source_column"])

    def test_same_cube_alias_chain_tracks_changes_to_dimension_sql(self):
        definitions = _renamed_definitions()
        dimensions = definitions["subscriptions"]["definition"]["dimensions"]
        dimensions[-1]["sql"] = "{subscriptions.account_alias}"
        dimensions.append(
            {"name": "account_alias", "sql": '{CUBE}."original_key"', "type": "string"}
        )
        self.assertEqual(
            "original_key", _catalog(definitions)["relationships"][0]["source_column"]
        )
        revised = copy.deepcopy(definitions)
        revised["subscriptions"]["definition"]["dimensions"][-1]["sql"] = '"new_key"'
        relationship = _catalog(revised)["relationships"][0]
        self.assertTrue(relationship["valid"])
        self.assertEqual("new_key", relationship["source_column"])
        self.assertEqual("{CUBE.account_id} = {accounts.id}", relationship["sql"])

    def test_computed_cross_cube_and_cyclic_keys_are_never_guessed(self):
        for expression in (
            'LOWER({CUBE}."billing_account_identifier")',
            "{accounts.id}",
            "{CUBE.account_id}",
            "{CUBE.missing}",
        ):
            with self.subTest(expression=expression):
                definitions = _renamed_definitions()
                definitions["subscriptions"]["definition"]["dimensions"][-1][
                    "sql"
                ] = expression
                relationship = _catalog(definitions)["relationships"][0]
                self.assertTrue(relationship["valid"])
                self.assertIsNone(relationship["source_column"])

    def test_physical_identifiers_preserve_quoting_and_postgres_case_folding(self):
        for source_sql, join_reference, physical_column in (
            ('{CUBE}."Billing ""ID"""', '{CUBE}."Billing ""ID"""', 'Billing "ID"'),
            ("Billing_ID", "{CUBE}.BILLING_ID", "billing_id"),
        ):
            with self.subTest(source_sql=source_sql):
                definitions = _renamed_definitions(
                    f"{join_reference} = {{accounts.id}}"
                )
                definitions["subscriptions"]["definition"]["dimensions"][-1][
                    "sql"
                ] = source_sql
                relationship = _catalog(definitions)["relationships"][0]
                self.assertTrue(relationship["valid"])
                self.assertEqual("account_id", relationship["source_member"])
                self.assertEqual(physical_column, relationship["source_column"])

    def test_semantic_member_parser_supports_reversed_and_mixed_references(self):
        for sql in (
            "{CUBE.account_id} = {accounts.id}",
            " {accounts.id} = {CUBE.account_id} ",
            "{subscriptions.account_id} = {accounts.id}",
            "{accounts}.id = {CUBE.account_id}",
            "{subscriptions}.account_id = {accounts.id}",
        ):
            with self.subTest(sql=sql):
                self.assertEqual(
                    ("account_id", "id"),
                    relationship_members(sql, "accounts", source_name="subscriptions"),
                )
        self.assertEqual(
            ("_key", "_id"),
            relationship_members("{CUBE._key} = {_accounts._id}", "_accounts"),
        )
        self.assertEqual(
            (None, None),
            relationship_members("{other.account_id} = {accounts.id}", "accounts"),
        )

    def test_join_authoring_rejects_non_member_expressions(self):
        for source, target, member in (
            ("account_id", "accounts} OR 1=1", "id"),
            ('"account_id"', "accounts", "id"),
            ("account_id", "accounts", "id + 1"),
        ):
            with self.subTest(source=source, target=target, member=member):
                with self.assertRaises(InvalidInputError):
                    relationship_join_sql(source, target, member)

    def test_authored_relationships_are_returned_when_cube_meta_omits_joins(self):
        definitions = {
            "accounts": _cube(
                "accounts",
                primary_key="account_id",
                connection_id=1,
            ),
            "subscriptions": _cube(
                "subscriptions",
                primary_key="subscription_id",
                connection_id=2,
                joins=[
                    {
                        "name": "accounts",
                        "sql": "{CUBE}.account_id = {accounts}.account_id",
                        "relationship": "many_to_one",
                    }
                ],
            ),
        }
        definitions["accounts"]["definition"]["dimensions"].append(
            {"name": "account_name", "sql": '"account_name"', "type": "string"}
        )
        definitions["subscriptions"]["definition"]["dimensions"].append(
            {"name": "account_id", "sql": '"account_id"', "type": "string"}
        )

        catalog = build_relationship_catalog(
            allowed_names={"accounts", "subscriptions"},
            definitions=definitions,
            compiled_names={"accounts", "subscriptions"},
            compiler_id="compiler-1",
        )

        self.assertTrue(catalog["valid"])
        self.assertEqual(1, catalog["relationship_count"])
        relationship = catalog["relationships"][0]
        self.assertEqual("subscriptions:accounts", relationship["id"])
        self.assertEqual("account_id", relationship["source_member"])
        self.assertEqual("account_id", relationship["target_member"])
        self.assertEqual("subscription_id", relationship["probe_source_member"])
        self.assertEqual("account_name", relationship["probe_target_member"])
        self.assertEqual(2, relationship["source_connection_id"])
        self.assertEqual(1, relationship["target_connection_id"])
        self.assertEqual("subscriptions", relationship["source_schema"])
        self.assertEqual("rows", relationship["source_table"])
        self.assertEqual("account_id", relationship["source_column"])
        self.assertTrue(relationship["models_compiled"])
        self.assertTrue(relationship["valid"])
        self.assertEqual([], relationship["issues"])

    def test_relationship_requires_collection_target_and_primary_key(self):
        definitions = {
            "subscriptions": _cube(
                "subscriptions",
                primary_key="subscription_id",
                joins=[
                    {
                        "name": "accounts",
                        "sql": "{CUBE}.account_id = {accounts}.account_id",
                        "relationship": "many_to_one",
                    }
                ],
            ),
        }
        definitions["subscriptions"]["definition"]["dimensions"].append(
            {"name": "account_id", "sql": '"account_id"', "type": "string"}
        )

        catalog = build_relationship_catalog(
            allowed_names={"subscriptions"},
            definitions=definitions,
            compiled_names={"subscriptions"},
        )

        self.assertFalse(catalog["valid"])
        self.assertEqual(
            ["TARGET_OUTSIDE_COLLECTION"],
            [issue["code"] for issue in catalog["relationships"][0]["issues"]],
        )

    def test_relationship_rejects_non_key_expression(self):
        definitions = {
            "accounts": _cube("accounts", primary_key="account_id"),
            "subscriptions": _cube(
                "subscriptions",
                primary_key="subscription_id",
                joins=[
                    {
                        "name": "accounts",
                        "sql": "LOWER({CUBE}.account_id) = {accounts}.account_id",
                        "relationship": "many_to_one",
                    }
                ],
            ),
        }

        catalog = build_relationship_catalog(
            allowed_names={"accounts", "subscriptions"},
            definitions=definitions,
            compiled_names={"accounts", "subscriptions"},
        )

        self.assertFalse(catalog["valid"])
        self.assertIn(
            "UNSUPPORTED_JOIN_EXPRESSION",
            [issue["code"] for issue in catalog["relationships"][0]["issues"]],
        )

    def test_relationship_members_accepts_reversed_equality(self):
        self.assertEqual(
            ("account_id", "account_id"),
            relationship_members(
                "{accounts}.account_id = {CUBE}.account_id",
                "accounts",
            ),
        )


class RelationshipExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_each_relationship_runs_a_bounded_cross_cube_query(self):
        catalog = {
            "valid": True,
            "relationships": [
                {
                    "id": "subscriptions:accounts",
                    "source_cube": "subscriptions",
                    "target_cube": "accounts",
                    "source_member": "account_id",
                    "target_member": "account_id",
                    "models_compiled": True,
                    "valid": True,
                }
            ],
        }
        execute = AsyncMock(return_value={"data": [{"accounts.account_id": "A1"}]})

        with patch(
            "app.semantic.relationships.execute_cube_query_payload",
            execute,
        ):
            result = await run_relationship_tests(
                catalog,
                allowed_names={"accounts", "subscriptions"},
            )

        self.assertTrue(result["valid"])
        self.assertEqual(1, result["tested_count"])
        execute.assert_awaited_once_with(
            {
                "query": {
                    "dimensions": [
                        "subscriptions.account_id",
                        "accounts.account_id",
                    ],
                    "limit": 1,
                }
            },
            allowed_names={"accounts", "subscriptions"},
        )

    async def test_invalid_relationship_is_not_executed(self):
        catalog = {
            "valid": False,
            "relationships": [
                {
                    "id": "subscriptions:accounts",
                    "source_cube": "subscriptions",
                    "target_cube": "accounts",
                    "source_member": None,
                    "target_member": None,
                    "models_compiled": True,
                    "valid": False,
                }
            ],
        }
        execute = AsyncMock()

        with patch(
            "app.semantic.relationships.execute_cube_query_payload",
            execute,
        ):
            result = await run_relationship_tests(
                catalog,
                allowed_names={"accounts", "subscriptions"},
            )

        self.assertFalse(result["valid"])
        self.assertEqual(
            "Relationship definition is invalid",
            result["relationships"][0]["error"],
        )
        execute.assert_not_awaited()


class RelationshipDataIntegrityTests(unittest.IsolatedAsyncioTestCase):
    async def test_semantic_joins_scan_resolved_physical_keys(self):
        pg = AsyncMock()
        pg.fetchrow.return_value = {
            field: 0
            for field in (
                "source_row_count",
                "target_row_count",
                "source_null_key_count",
                "target_null_key_count",
                "unmatched_source_row_count",
                "duplicate_source_key_count",
                "duplicate_target_key_count",
            )
        }

        @asynccontextmanager
        async def destination(_runtime):
            yield pg

        with patch("app.relationship_service._destination_connection", destination):
            result = await validate_relationship_data(
                _collection(), _catalog(_renamed_definitions())
            )
        self.assertTrue(result["valid"])
        query = pg.fetchrow.await_args.args[0]
        self.assertIn('"billing_account_identifier"', query)
        self.assertIn('"CRM Account ID"', query)
        self.assertNotIn('"account_id"', query)
        self.assertNotIn('"id"', query)

    async def test_unresolved_or_invalid_keys_never_scan_guessed_columns(self):
        for expression, sql, error in (
            (
                'LOWER("billing_account_identifier")',
                "{CUBE.account_id} = {accounts.id}",
                "physical keys could not be resolved",
            ),
            (
                '"billing_account_identifier"',
                "{CUBE}.account_id = {accounts}.id",
                "definition is invalid",
            ),
        ):
            with self.subTest(expression=expression, sql=sql):
                definitions = _renamed_definitions(sql)
                definitions["subscriptions"]["definition"]["dimensions"][-1][
                    "sql"
                ] = expression
                connect = AsyncMock()
                with patch("app.relationship_service._destination_connection", connect):
                    result = await validate_relationship_data(
                        _collection(), _catalog(definitions)
                    )
                self.assertFalse(result["valid"])
                self.assertIn(error, result["relationships"][0]["error"])
                connect.assert_not_called()

    async def test_many_to_one_allows_source_duplicates_and_reports_orphans(self):
        class Database:
            async def fetchrow(self, _query):
                return {
                    "source_row_count": 40,
                    "target_row_count": 10,
                    "source_null_key_count": 0,
                    "target_null_key_count": 0,
                    "unmatched_source_row_count": 1,
                    "duplicate_source_key_count": 8,
                    "duplicate_target_key_count": 0,
                }

        @asynccontextmanager
        async def destination(_runtime):
            yield Database()

        with patch("app.relationship_service._destination_connection", destination):
            result = await validate_relationship_data(
                _collection(),
                _physical_catalog(),
            )

        relationship = result["relationships"][0]
        self.assertTrue(result["valid"])
        self.assertTrue(relationship["valid"])
        self.assertEqual(1, relationship["unmatched_source_row_count"])
        self.assertEqual(8, relationship["duplicate_source_key_count"])

    async def test_many_to_one_rejects_duplicate_target_keys(self):
        class Database:
            async def fetchrow(self, _query):
                return {
                    "source_row_count": 40,
                    "target_row_count": 10,
                    "source_null_key_count": 0,
                    "target_null_key_count": 0,
                    "unmatched_source_row_count": 0,
                    "duplicate_source_key_count": 8,
                    "duplicate_target_key_count": 1,
                }

        @asynccontextmanager
        async def destination(_runtime):
            yield Database()

        with patch("app.relationship_service._destination_connection", destination):
            result = await validate_relationship_data(
                _collection(),
                _physical_catalog(),
            )

        relationship = result["relationships"][0]
        self.assertFalse(result["valid"])
        self.assertFalse(relationship["valid"])
        self.assertEqual(
            "Snapshot keys do not satisfy the declared cardinality",
            relationship["error"],
        )


def _collection() -> dict:
    return {
        "pipes": [
            {
                "id": 1,
                "slug": "accounts",
                "destination_id": 1,
                "destination_schema": "accounts",
            },
            {
                "id": 2,
                "slug": "subscriptions",
                "destination_id": 1,
                "destination_schema": "subscriptions",
            },
        ]
    }


def _physical_catalog() -> dict:
    return {
        "relationships": [
            {
                "id": "subscriptions:accounts",
                "relationship": "many_to_one",
                "valid": True,
                "source_connection_id": 2,
                "target_connection_id": 1,
                "source_schema": "subscriptions",
                "source_table": "rows",
                "source_column": "account_id",
                "target_schema": "accounts",
                "target_table": "rows",
                "target_column": "account_id",
            }
        ]
    }


if __name__ == "__main__":
    unittest.main()
