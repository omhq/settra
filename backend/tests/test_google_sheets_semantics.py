import unittest

from app.common.config import GOOGLE_DRIVE_CONFIG_DIR


class GoogleSheetsSemanticsTests(unittest.TestCase):
    def test_connector_does_not_ship_default_semantic_models(self):
        self.assertEqual([], list(GOOGLE_DRIVE_CONFIG_DIR.glob("semantics.y*ml")))

if __name__ == "__main__":
    unittest.main()
