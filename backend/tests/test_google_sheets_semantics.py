import os
import unittest

import yaml

from app.routers.constants import CONNECTORS_DIR


def _load_google_sheets_semantics(testcase: unittest.TestCase):
    if "CONNECTORS_DIR" not in os.environ:
        testcase.skipTest("set CONNECTORS_DIR to check the Google Sheets template")

    path = CONNECTORS_DIR / "googlesheets" / "semantics.yaml"

    if not path.is_file():
        testcase.skipTest("Google Sheets template is not mounted in this context")

    return yaml.safe_load(path.read_text(encoding="utf-8"))


class GoogleSheetsSemanticsTests(unittest.TestCase):
    def test_contains_only_google_sheets_source_tables(self):
        parsed = _load_google_sheets_semantics(self)
        cubes = parsed["cubes"]

        self.assertEqual(
            {
                "googlesheets_spreadsheet",
                "googlesheets_sheet",
                "googlesheets_cell",
            },
            {cube["name"] for cube in cubes},
        )
        self.assertTrue(
            all(
                cube["sql_table"].startswith('"googlesheets"."googlesheets_')
                for cube in cubes
            )
        )

    def test_raw_cells_explain_record_counting_caveat(self):
        parsed = _load_google_sheets_semantics(self)
        cells = next(
            cube for cube in parsed["cubes"] if cube["name"] == "googlesheets_cell"
        )
        dimensions = {item["name"]: item for item in cells["dimensions"]}

        self.assertIn("not one row per worksheet record", cells["description"])
        self.assertTrue(dimensions["cell"]["primary_key"])
        self.assertEqual("count", cells["measures"][0]["type"])


if __name__ == "__main__":
    unittest.main()
