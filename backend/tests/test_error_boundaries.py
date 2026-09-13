import ast
import json
import unittest
from pathlib import Path

from app.cube.client import CubeAPIError
from app.errors import (
    AccessDeniedError,
    InvalidInputError,
    InvalidOperationError,
    ResourceConflictError,
    ResourceNotFoundError,
)
from app.routers.error_handlers import (
    application_error_handler,
    cube_api_error_handler,
)


class DomainErrorBoundaryTests(unittest.TestCase):
    def test_backend_uses_the_pinned_python_annotation_syntax(self):
        backend_dir = Path(__file__).resolve().parents[1]

        for path in backend_dir.rglob("*.py"):
            with self.subTest(path=path.relative_to(backend_dir)):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                future_annotations = [
                    alias
                    for node in ast.walk(tree)
                    if isinstance(node, ast.ImportFrom) and node.module == "__future__"
                    for alias in node.names
                    if alias.name == "annotations"
                ]
                self.assertEqual([], future_annotations)

    def test_reusable_semantic_modules_do_not_import_fastapi(self):
        app_dir = Path(__file__).resolve().parents[1] / "app"
        paths = [
            *(app_dir / "semantic").glob("*.py"),
            *(app_dir / "cube").glob("*.py"),
            app_dir / "collection_service.py",
            app_dir / "calculation_service.py",
        ]

        for path in paths:
            with self.subTest(path=path.relative_to(app_dir)):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                imported_modules = {
                    node.module
                    for node in ast.walk(tree)
                    if isinstance(node, ast.ImportFrom) and node.module
                }
                imported_modules.update(
                    alias.name
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Import)
                    for alias in node.names
                )
                self.assertFalse(
                    any(
                        module == "fastapi" or module.startswith("fastapi.")
                        for module in imported_modules
                    )
                )


class HTTPErrorMappingTests(unittest.IsolatedAsyncioTestCase):
    async def test_application_errors_map_to_stable_http_responses(self):
        cases = (
            (InvalidOperationError("cannot do that"), 400),
            (InvalidInputError("invalid input"), 422),
            (ResourceNotFoundError("missing"), 404),
            (ResourceConflictError("already exists"), 409),
            (AccessDeniedError("forbidden"), 403),
        )

        for error, expected_status in cases:
            with self.subTest(error=error.__class__.__name__):
                response = await application_error_handler(None, error)

                self.assertEqual(expected_status, response.status_code)
                self.assertEqual(
                    {"detail": error.message},
                    json.loads(response.body),
                )

    async def test_cube_errors_preserve_status_and_retryability(self):
        response = await cube_api_error_handler(
            None,
            CubeAPIError("Cube is unavailable", status_code=503),
        )

        self.assertEqual(503, response.status_code)
        self.assertEqual(
            {
                "detail": {
                    "message": "Cube is unavailable",
                    "retryable": True,
                }
            },
            json.loads(response.body),
        )


if __name__ == "__main__":
    unittest.main()
