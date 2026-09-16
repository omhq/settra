import unittest

from app.cube.identifiers import cube_sql_alias
from app.errors import InvalidOperationError


class CubeSQLAliasTests(unittest.TestCase):
    def test_exact_postgres_boundary_does_not_require_an_alias(self):
        self.assertIsNone(cube_sql_alias("c" * 13, ["a" * 48]))
        self.assertEqual(13, len(cube_sql_alias("c" * 14, ["a" * 48])))

    def test_long_models_remain_distinct_and_deterministic(self):
        first_name = "collection_1_0123456789abcdef"
        second_name = "collection_1_0123456789abcdee"
        first = cube_sql_alias(first_name, ["a" * 48])
        second = cube_sql_alias(second_name, ["a" * 48])
        self.assertEqual(first, cube_sql_alias(first_name, ["a" * 48]))
        self.assertNotEqual(first, second)
        self.assertLessEqual(len(first) + 2 + 48, 63)
        self.assertLessEqual(len(second) + 2 + 48, 63)

    def test_cube_name_normalization_and_member_capitals_are_budgeted(self):
        member = "a" * 46 + "B"
        alias = cube_sql_alias("Collection_1_0123456789abcdef", [member])
        self.assertEqual(13, len(alias))
        self.assertEqual(alias.lower(), alias)
        # Cube inserts an underscore before B: 47 public characters become 48.
        self.assertEqual(63, len(alias) + 2 + 48)

    def test_postgres_limit_counts_utf8_bytes(self):
        member = "é" * 24
        alias = cube_sql_alias("collection_1_0123456789abcdef", [member])
        self.assertLessEqual(
            len(alias.encode("utf-8")) + 2 + len(member.encode("utf-8")), 63
        )

    def test_unbudgetable_members_fail_explicitly(self):
        with self.assertRaisesRegex(InvalidOperationError, "Shorten Cube member names"):
            cube_sql_alias("collection_1_0123456789abcdef", ["a" * 63])
