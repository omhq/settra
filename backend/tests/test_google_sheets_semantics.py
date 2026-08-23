import tempfile
import unittest

from pathlib import Path
from unittest.mock import patch

from app.cube import model
from app.routers.constants import GOOGLE_SHEETS_CONFIG_DIR


class GoogleSheetsSemanticsTests(unittest.TestCase):
    def test_connector_does_not_ship_default_semantic_models(self):
        self.assertEqual([], list(GOOGLE_SHEETS_CONFIG_DIR.glob("semantics.y*ml")))

    def test_startup_removes_legacy_default_models_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            model_dir = Path(temp_dir)
            legacy = model_dir / "googlesheets.yaml"
            generated = model_dir / "generated" / "connections" / "source.yaml"
            legacy.write_text("cubes: []\n", encoding="utf-8")
            generated.parent.mkdir(parents=True)
            generated.write_text("cubes: []\n", encoding="utf-8")

            with patch.object(model, "CUBE_MODEL_DIR", model_dir):
                removed = model._remove_legacy_default_models()

            self.assertEqual(["googlesheets.yaml"], removed)
            self.assertFalse(legacy.exists())
            self.assertTrue(generated.exists())


if __name__ == "__main__":
    unittest.main()
