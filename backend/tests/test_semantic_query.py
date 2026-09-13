import unittest

from fastapi import HTTPException

from app.semantic.query import referenced_cube_names, validate_cube_query_names


class SemanticQueryReferenceTests(unittest.TestCase):
    def test_finds_references_across_all_supported_query_locations(self):
        query = {
            "measures": ["orders.revenue"],
            "filters": [
                {
                    "member": "customers.email",
                    "operator": "equals",
                    "values": ["person@example.com"],
                }
            ],
            "timeDimensions": [
                {
                    "dimension": "orders.created_at",
                    "dateRange": ["2026-01-01", "2026-01-31"],
                }
            ],
            "order": {"orders.created_at": "desc"},
            "joinHints": ["customers"],
        }

        self.assertEqual(
            {"customers", "orders"},
            referenced_cube_names(query),
        )

    def test_handles_cube_blending_without_treating_values_as_members(self):
        query = [
            {"dimensions": ["orders.status"]},
            {
                "measures": ["targets.amount"],
                "filters": [
                    {
                        "member": "targets.region",
                        "operator": "equals",
                        "values": ["north.america"],
                    }
                ],
            },
        ]

        self.assertEqual({"orders", "targets"}, referenced_cube_names(query))

    def test_access_validation_uses_the_same_reference_extractor(self):
        with self.assertRaises(HTTPException) as raised:
            validate_cube_query_names(
                {"order": {"private_orders.created_at": "desc"}},
                {"orders"},
            )

        self.assertEqual(404, raised.exception.status_code)
        self.assertIn("private_orders", str(raised.exception.detail))


if __name__ == "__main__":
    unittest.main()
