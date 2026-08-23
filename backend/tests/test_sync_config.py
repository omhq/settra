import os
import tempfile
import unittest

from pathlib import Path
from unittest.mock import AsyncMock, patch

import yaml

from fastapi import HTTPException

from app.cube.client import CubeAPIError
from app.cube.model import render_connection_manifest_model
from app.sync import config as sync_config
from app.sync import loader as sync_loader
from app.sync import secrets as sync_secrets


class SyncConfigTests(unittest.TestCase):
    def test_default_is_durable_full_replace_without_secrets(self):
        config = sync_config.default_sync_config(
            slug="sales_forecast",
            spreadsheet_id="sheet-123",
            sheets="Sales, Forecast *",
        )

        parsed = sync_config.validate_sync_config(
            config,
            expected_slug="sales_forecast",
        )

        self.assertEqual("postgres", parsed["destination"]["type"])
        self.assertEqual(
            "built_in_postgres",
            parsed["destination"]["key"],
        )
        self.assertEqual("google_drive", parsed["source"]["type"])
        self.assertEqual("sheet-123", parsed["source"]["file_id"])
        self.assertEqual("auto", parsed["source"]["format"])
        self.assertEqual("sales_forecast", parsed["destination"]["schema"])
        self.assertEqual("replace", parsed["load"]["write_disposition"])
        self.assertEqual(
            "insert-from-staging",
            parsed["load"]["replace_strategy"],
        )
        self.assertEqual(["Sales", "Forecast *"], parsed["source"]["sheets"])
        self.assertNotIn("credentials", yaml.safe_dump(parsed))
        self.assertNotIn("refresh_token", yaml.safe_dump(parsed))

    def test_legacy_google_sheet_yaml_is_upgraded_without_changing_header_behavior(
        self,
    ):
        parsed = sync_config.validate_sync_config(
            {
                "version": 1,
                "source": {
                    "type": "google_sheets",
                    "spreadsheet_id": "sheet-123",
                    "sheets": ["*"],
                },
                "destination": {"type": "postgres", "schema": "sales"},
                "load": {
                    "write_disposition": "replace",
                    "replace_strategy": "insert-from-staging",
                },
                "schema": {"tables": {}},
            },
            expected_slug="sales",
        )

        self.assertEqual("google_drive", parsed["source"]["type"])
        self.assertEqual("sheet-123", parsed["source"]["file_id"])
        self.assertEqual("google_sheets", parsed["source"]["format"])
        self.assertEqual(1, parsed["source"]["parsing"]["header_row"])
        self.assertNotIn("spreadsheet_id", parsed["source"])

    def test_parsing_and_per_table_header_overrides_are_validated(self):
        config = sync_config.default_sync_config(
            slug="sales",
            file_id="file-123",
            file_name="sales.csv",
            mime_type="text/csv",
        )
        config["source"]["format"] = "csv"
        config["source"]["parsing"] = {
            "delimiter": "semicolon",
            "encoding": "cp1252",
            "header_row": 2,
        }
        config["schema"]["tables"] = {"sales": {"header_row": 3}}

        parsed = sync_config.validate_sync_config(config, expected_slug="sales")

        self.assertEqual(";", parsed["source"]["parsing"]["delimiter"])
        self.assertEqual(2, parsed["source"]["parsing"]["header_row"])
        self.assertEqual(3, parsed["schema"]["tables"]["sales"]["header_row"])

        config["source"]["parsing"]["header_row"] = 0

        with self.assertRaises(HTTPException):
            sync_config.validate_sync_config(config, expected_slug="sales")

    def test_detected_values_fill_auto_yaml_without_overwriting_user_values(self):
        config = sync_config.default_sync_config(
            slug="sales",
            file_id="file-123",
        )
        config["source"]["parsing"]["encoding"] = "cp1252"

        updated = sync_config.apply_detected_source_config(
            config,
            {
                "file_name": "sales.csv",
                "mime_type": "text/csv",
                "format": "csv",
                "parsing": {
                    "encoding": "utf-8",
                    "delimiter": ",",
                    "header_row": 2,
                },
            },
        )

        self.assertEqual("csv", updated["source"]["format"])
        self.assertEqual("sales.csv", updated["source"]["file_name"])
        self.assertEqual("cp1252", updated["source"]["parsing"]["encoding"])
        self.assertEqual(",", updated["source"]["parsing"]["delimiter"])
        self.assertEqual(2, updated["source"]["parsing"]["header_row"])

    def test_destination_schema_cannot_escape_the_connection(self):
        config = sync_config.default_sync_config(
            slug="sales",
            spreadsheet_id="sheet-123",
        )
        config["destination"]["schema"] = "other"

        with self.assertRaises(HTTPException) as raised:
            sync_config.validate_sync_config(config, expected_slug="sales")

        self.assertEqual(422, raised.exception.status_code)

    def test_destination_identity_and_target_schema_are_locked_separately(self):
        config = sync_config.default_sync_config(
            slug="source_sales",
            file_id="file-123",
            destination_key="built_in_postgres",
            destination_schema="warehouse_sales",
        )

        parsed = sync_config.validate_sync_config(
            config,
            expected_destination_key="built_in_postgres",
            expected_destination_schema="warehouse_sales",
        )

        self.assertEqual("file-123", parsed["source"]["file_id"])
        self.assertEqual("warehouse_sales", parsed["destination"]["schema"])

        config["destination"]["key"] = "external_warehouse"

        with self.assertRaises(HTTPException):
            sync_config.validate_sync_config(
                config,
                expected_destination_key="built_in_postgres",
                expected_destination_schema="warehouse_sales",
            )

    def test_validates_type_overrides_and_contract_modes(self):
        config = sync_config.default_sync_config(
            slug="sales",
            spreadsheet_id="sheet-123",
        )
        config["schema"]["tables"] = {
            "Orders": {
                "description": "One row per order",
                "columns": {
                    "Order ID": {
                        "name": "order_id",
                        "data_type": "bigint",
                        "description": "Stable identifier",
                    }
                },
            }
        }
        parsed = sync_config.validate_sync_config(config, expected_slug="sales")
        self.assertEqual(
            "bigint",
            parsed["schema"]["tables"]["Orders"]["columns"]["Order ID"]["data_type"],
        )

        config["schema"]["tables"]["Orders"]["columns"]["Order ID"][
            "data_type"
        ] = "uuid"

        with self.assertRaises(HTTPException):
            sync_config.validate_sync_config(config, expected_slug="sales")


class OAuthSecretTests(unittest.IsolatedAsyncioTestCase):
    async def test_google_refresh_token_round_trips_encrypted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "google.enc"
            with (
                patch.object(sync_secrets, "GOOGLE_OAUTH_CREDENTIALS_PATH", path),
                patch.dict(os.environ, {"SECRET_KEY": "test-secret"}),
            ):
                await sync_secrets.save_google_oauth_secret(
                    {"refresh_token": "refresh-me", "email": "user@example.com"}
                )
                raw = path.read_bytes()
                mode = path.stat().st_mode & 0o777
                loaded = await sync_secrets.load_google_oauth_secret()

        self.assertNotIn(b"refresh-me", raw)
        self.assertEqual("refresh-me", loaded["refresh_token"])
        self.assertEqual(0o600, mode)


class ManifestCubeModelTests(unittest.TestCase):
    def test_manifest_generates_postgres_cube_with_typed_dimensions(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "sales.manifest.yaml"
            manifest_path.write_text(
                yaml.safe_dump(
                    {
                        "generated_at": "2026-08-21T00:00:00+00:00",
                        "tables": [
                            {
                                "name": "orders",
                                "source_sheet": "Orders",
                                "description": "One row per order",
                                "columns": [
                                    {
                                        "name": "order_id",
                                        "type": "bigint",
                                        "description": "Identifier",
                                    },
                                    {"name": "ordered_at", "type": "date"},
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            rendered = render_connection_manifest_model(
                manifest_path,
                {
                    "id": 7,
                    "name": "Sales",
                    "slug": "sales",
                    "destination_schema": "warehouse_sales",
                },
            )

        model = yaml.safe_load(rendered)
        cube = model["cubes"][0]
        dimensions = {item["name"]: item for item in cube["dimensions"]}
        self.assertEqual('"warehouse_sales"."orders"', cube["sql_table"])
        self.assertEqual("number", dimensions["order_id"]["type"])
        self.assertEqual("time", dimensions["ordered_at"]["type"])
        self.assertEqual("One row per order", cube["description"])
        self.assertEqual("Identifier", dimensions["order_id"]["description"])
        self.assertEqual("postgres", cube["meta"]["settra"]["storage"])

    def test_manifest_omits_empty_cube_and_dimension_descriptions(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "bank.manifest.yaml"
            manifest_path.write_text(
                yaml.safe_dump(
                    {
                        "tables": [
                            {
                                "name": "transactions",
                                "description": "",
                                "columns": [
                                    {
                                        "name": "memo",
                                        "type": "text",
                                        "description": "   ",
                                    }
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            rendered = render_connection_manifest_model(
                manifest_path,
                {"id": 8, "name": "Bank", "slug": "bank"},
            )

        cube = yaml.safe_load(rendered)["cubes"][0]
        self.assertNotIn("description", cube)
        self.assertNotIn("description", cube["dimensions"][0])


class PostSyncSemanticValidationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        sync_loader._SYNC_LOCKS.clear()

    async def test_refresh_rejects_a_cube_compile_failure(self):
        connection = {
            "id": 8,
            "slug": "bank",
            "plugin": "googledrive",
        }

        with (
            patch(
                "app.agent.metadata.get_schema_with_descriptions",
                new=AsyncMock(return_value={"tables": []}),
            ),
            patch(
                "app.routers.connection_metadata.write_connection_metadata_cache",
                new=AsyncMock(),
            ),
            patch(
                "app.cube.model.sync_connection_models",
                new=AsyncMock(return_value={"written": []}),
            ),
            patch(
                "app.cube.client.load_cube_meta",
                new=AsyncMock(
                    side_effect=CubeAPIError(
                        "Compile errors: invalid generated cube",
                        status_code=500,
                    )
                ),
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                await sync_loader._refresh_models_and_metadata(connection)

        self.assertEqual(502, raised.exception.status_code)
        self.assertIn("PostgreSQL sync completed", str(raised.exception.detail))
        self.assertIn("Compile errors", str(raised.exception.detail))

    async def test_sync_preserves_loaded_counts_when_cube_validation_fails(self):
        result = {
            "table_count": 1,
            "row_count": 102,
            "load_ids": ["load-1"],
        }
        finish_run = AsyncMock()

        with (
            patch(
                "app.sync.loader._connection",
                new=AsyncMock(
                    return_value={
                        "id": 8,
                        "slug": "bank",
                        "plugin": "googledrive",
                    }
                ),
            ),
            patch(
                "app.sync.loader.read_sync_config",
                new=AsyncMock(return_value={"source": {}}),
            ),
            patch(
                "app.sync.loader.load_google_oauth_secret",
                new=AsyncMock(return_value={"scopes": [sync_loader.GOOGLE_FILE_SCOPE]}),
            ),
            patch("app.sync.loader._start_run", new=AsyncMock(return_value=12)),
            patch(
                "app.sync.loader.asyncio.to_thread",
                new=AsyncMock(return_value=result),
            ),
            patch(
                "app.sync.loader._refresh_models_and_metadata",
                new=AsyncMock(
                    side_effect=HTTPException(502, "Cube compilation failed")
                ),
            ),
            patch("app.sync.loader._finish_run", new=finish_run),
        ):
            with self.assertRaises(HTTPException):
                await sync_loader.run_connection_sync(8)

        finish_run.assert_awaited_once_with(
            12,
            8,
            result=result,
            error="Cube compilation failed",
        )


if __name__ == "__main__":
    unittest.main()
