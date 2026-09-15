import unittest
from unittest.mock import patch

from app.semantic.catalog import allowed_cube_names_for_pipe_ids


def source(name, pipe_id):
    return {
        "source_type": "generated_connection",
        "definition": {
            "name": name,
            "sql_table": f'"pipe_{pipe_id}"."rows"',
            "meta": {"settra": {"connection_id": pipe_id}},
        },
    }


def overlay(name, *, pipe_ids=(), dependencies=(), schema=None):
    definition = {
        "name": name,
        "meta": {"settra": {"connection_ids": list(pipe_ids)}},
        "joins": [{"name": dependency} for dependency in dependencies],
    }
    if schema:
        definition["sql_table"] = f"{schema}.rows"
    return {"source_type": "generated_overlay", "definition": definition}


def view(name, path):
    return {
        "source_type": "generated_overlay",
        "definition": {
            "name": name,
            "cubes": [{"join_path": path, "includes": "*"}],
        },
    }


class SemanticVisibilityTests(unittest.TestCase):
    def setUp(self):
        self.models = {
            "orders": source("orders", 1),
            "customers": source("customers", 2),
        }

    def visible(self, pipes):
        namespaces = {pipe_id: f"pipe_{pipe_id}" for pipe_id in pipes}
        with patch(
            "app.semantic.catalog.authored_definition_index", return_value=self.models
        ):
            forward = allowed_cube_names_for_pipe_ids(
                set(pipes), pipe_namespaces=namespaces
            )
        with patch(
            "app.semantic.catalog.authored_definition_index",
            return_value=dict(reversed(list(self.models.items()))),
        ):
            self.assertEqual(
                forward,
                allowed_cube_names_for_pipe_ids(set(pipes), pipe_namespaces=namespaces),
            )
        return forward

    def test_in_scope_dependency_cannot_authorize_foreign_physical_provenance(self):
        self.models["customer_orders"] = overlay(
            "customer_orders", pipe_ids=[2], dependencies=["orders"], schema="pipe_2"
        )
        self.models["customer_view"] = view("customer_view", "customer_orders")
        self.models["outer_view"] = view("outer_view", "customer_view")
        self.assertEqual({"orders"}, self.visible([1]))
        self.assertEqual(set(self.models), self.visible([1, 2]))

    def test_foreign_dependency_removes_source_model_and_all_derived_models(self):
        self.models["joined_orders"] = overlay(
            "joined_orders", pipe_ids=[1], dependencies=["customers"], schema="pipe_1"
        )
        self.models["report"] = view("report", "joined_orders")
        self.assertEqual({"orders"}, self.visible([1]))
        self.assertEqual(set(self.models), self.visible([1, 2]))

    def test_physical_namespace_is_required_when_metadata_is_missing_or_stale(self):
        for declared_ids in ([], [1]):
            with self.subTest(declared_ids=declared_ids):
                self.models["foreign"] = overlay(
                    "foreign",
                    pipe_ids=declared_ids,
                    dependencies=["orders"],
                    schema="pipe_2",
                )
                self.assertEqual({"orders"}, self.visible([1]))
                self.assertIn("foreign", self.visible([1, 2]))

    def test_unknown_physical_namespace_is_not_authorized_by_claimed_ids(self):
        self.models["unknown"] = overlay(
            "unknown", pipe_ids=[1], dependencies=["orders"], schema="unknown_pipe"
        )
        self.assertEqual({"orders"}, self.visible([1]))

    def test_all_explicit_source_ids_must_be_in_scope(self):
        self.models["combined"] = overlay(
            "combined", pipe_ids=[1, 2], dependencies=["orders"], schema="pipe_1"
        )
        self.assertEqual({"orders"}, self.visible([1]))
        self.assertIn("combined", self.visible([1, 2]))

    def test_every_cube_in_view_join_path_must_be_visible(self):
        self.models["joined_view"] = view("joined_view", "orders.customers")
        self.assertEqual({"orders"}, self.visible([1]))
        self.assertEqual(set(self.models), self.visible([1, 2]))

    def test_source_backed_cycles_are_supported_but_foreign_cycles_are_excluded(self):
        self.models["a"] = overlay(
            "a", pipe_ids=[1], dependencies=["b"], schema="pipe_1"
        )
        self.models["b"] = overlay("b", dependencies=["a"])
        self.models["report"] = view("report", "b")
        self.assertEqual({"orders", "a", "b", "report"}, self.visible([1]))
        self.models["b"] = overlay(
            "b", pipe_ids=[2], dependencies=["a"], schema="pipe_2"
        )
        self.assertEqual({"orders"}, self.visible([1]))
        self.assertEqual(set(self.models), self.visible([1, 2]))

    def test_missing_dependencies_and_ungrounded_cycles_are_excluded(self):
        self.models["missing"] = overlay(
            "missing", pipe_ids=[1], dependencies=["does_not_exist"]
        )
        self.models["a"] = overlay("a", dependencies=["b"])
        self.models["b"] = overlay("b", dependencies=["a"])
        self.models["report"] = view("report", "missing")
        self.assertEqual({"orders"}, self.visible([1]))
        self.assertEqual(set(), self.visible([]))

    def test_inheritance_and_member_expressions_obey_transitive_scope(self):
        self.models["derived"] = {
            "source_type": "generated_overlay",
            "definition": {
                "name": "derived",
                "extends": "orders",
                "dimensions": [
                    {"name": "name", "sql": "{customers.name}", "type": "string"},
                ],
            },
        }
        self.models["report"] = view("report", "derived")
        self.assertEqual({"orders"}, self.visible([1]))
        self.assertEqual(set(self.models), self.visible([1, 2]))

    def test_registered_namespace_remains_authoritative_without_generated_models(self):
        self.models = {"owned": overlay("owned", schema="pipe_1")}
        self.assertEqual({"owned"}, self.visible([1]))
        self.assertEqual(set(), self.visible([2]))
