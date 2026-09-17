import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.cube.model_repository import CubeModelRepository
from app.errors import ResourceConflictError

INITIAL = "cubes:\n  - name: orders\n    sql_table: public.orders\n"
UPDATED = "cubes:\n  - name: orders_v2\n    sql_table: public.orders\n"


class CubeModelRepositoryAtomicWriteTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.repository = CubeModelRepository(self.root)

    def temporary_files(self) -> list[Path]:
        return list(self.root.rglob("*.tmp"))

    def test_failed_replacement_preserves_the_complete_previous_document(self):
        self.repository.save("generated/connections/orders.yaml", INITIAL)

        with (
            patch(
                "app.cube.model_repository.os.replace",
                side_effect=OSError("simulated replacement failure"),
            ),
            self.assertRaisesRegex(OSError, "simulated replacement failure"),
        ):
            self.repository.update("generated/connections/orders.yaml", UPDATED)

        self.assertEqual(
            INITIAL,
            self.repository.read("generated/connections/orders.yaml")["content"],
        )
        self.assertEqual([], self.temporary_files())

    def test_exclusive_create_never_replaces_an_existing_document(self):
        path = "overlays/generated/organizations/1/existing.yaml"
        self.repository.create(path, INITIAL)

        with self.assertRaises(ResourceConflictError):
            self.repository.create(path, UPDATED)

        self.assertEqual(INITIAL, self.repository.read(path)["content"])
        self.assertEqual([], self.temporary_files())

    def test_atomic_save_publishes_the_complete_new_document(self):
        path = "generated/connections/orders.yaml"
        self.repository.save(path, INITIAL)
        self.repository.save(path, UPDATED)

        self.assertEqual(UPDATED, self.repository.read(path)["content"])
        self.assertEqual(
            0o644,
            stat.S_IMODE(self.repository.safe_path(path).stat().st_mode),
        )
        self.assertEqual([], self.temporary_files())


if __name__ == "__main__":
    unittest.main()
