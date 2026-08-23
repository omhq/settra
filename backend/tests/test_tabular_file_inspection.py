import io
import unittest

from app.sync import loader
from app.sync.config import default_sync_config, validate_sync_config
from app.sync.inspection import (
    GoogleDriveFile,
    TabularFileInspector,
    TabularInspection,
    display_delimiter,
)


class TabularFileInspectorTests(unittest.TestCase):
    def setUp(self):
        self.inspector = TabularFileInspector()

    def test_detects_supported_formats_from_drive_metadata_and_extension(self):
        cases = [
            (
                GoogleDriveFile(
                    "1",
                    "Sales",
                    "application/vnd.google-apps.spreadsheet",
                ),
                "google_sheets",
            ),
            (GoogleDriveFile("2", "sales.csv", "text/csv"), "csv"),
            (GoogleDriveFile("2b", "sales.csv", "application/vnd.ms-excel"), "csv"),
            (
                GoogleDriveFile("3", "sales.xlsx", "application/octet-stream"),
                "excel",
            ),
            (
                GoogleDriveFile("4", "sales.parquet", "application/octet-stream"),
                "parquet",
            ),
        ]

        for file, expected in cases:
            with self.subTest(name=file.name):
                self.assertEqual(expected, self.inspector.detect_format(file))

    def test_detects_csv_encoding_delimiter_and_leading_header_row(self):
        content = (
            "Sales export;;\r\n"
            ";;\r\n"
            "Order ID;Customer;Amount\r\n"
            "1001;Ada;10.25\r\n"
            "1002;Grace;12.50\r\n"
        ).encode("utf-8")

        encoding, delimiter, rows, header_row = self.inspector.inspect_delimited(
            content,
            file_name="sales.csv",
            parsing={
                "encoding": "auto",
                "delimiter": "auto",
                "header_row": "auto",
            },
        )

        self.assertEqual("utf-8", encoding)
        self.assertEqual(";", delimiter)
        self.assertEqual(3, header_row)
        self.assertEqual("Order ID", rows[header_row - 1][0])

    def test_respects_explicit_csv_overrides(self):
        content = "ignore\nname|amount\nAda|10\n".encode("cp1252")

        encoding, delimiter, _rows, header_row = self.inspector.inspect_delimited(
            content,
            file_name="sales.txt",
            parsing={
                "encoding": "cp1252",
                "delimiter": "pipe",
                "header_row": 2,
            },
        )

        self.assertEqual("cp1252", encoding)
        self.assertEqual("|", delimiter)
        self.assertEqual("|", display_delimiter(delimiter))
        self.assertEqual(2, header_row)

    def test_rejects_known_non_tabular_drive_files(self):
        file = GoogleDriveFile("pdf-1", "report.pdf", "application/pdf")

        with self.assertRaisesRegex(ValueError, "Unsupported Google Drive file type"):
            self.inspector.detect_format(file, content=b"%PDF-1.7\n")


class TabularParserTests(unittest.TestCase):
    def test_csv_parser_normalizes_detected_header_and_rows(self):
        config = validate_sync_config(
            default_sync_config(slug="orders", file_id="csv-1"),
            expected_slug="orders",
        )
        file = GoogleDriveFile("csv-1", "orders.csv", "text/csv")
        inspection = TabularInspection(file=file, format="csv")

        tables = loader._extract_csv(
            config,
            file,
            b"Report generated today,,\nOrder ID,Amount,Active\n1,10.5,true\n",
            TabularFileInspector(),
            inspection,
            set(),
        )

        self.assertEqual("orders", tables[0]["table_name"])
        self.assertEqual(2, inspection.parsing["header_row"])
        self.assertEqual(
            {"order_id": "1", "amount": "10.5", "active": "true"},
            tables[0]["rows"][0],
        )

    def test_excel_parser_reads_workbook_worksheets(self):
        import openpyxl

        workbook = openpyxl.Workbook()
        workbook.active.title = "Orders"
        workbook.active.append(["Order ID", "Amount"])
        workbook.active.append([1, 10.5])
        workbook.create_sheet("Forecast").append(["Month", "Target"])
        output = io.BytesIO()
        workbook.save(output)
        workbook.close()

        worksheets = loader._read_excel_worksheets(
            GoogleDriveFile(
                "excel-1",
                "sales.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
            output.getvalue(),
        )

        self.assertEqual(["Orders", "Forecast"], [name for name, _ in worksheets])
        self.assertEqual([1, 10.5], worksheets[0][1][1])

    def test_parquet_parser_preserves_compatible_column_types(self):
        import pyarrow as arrow
        import pyarrow.parquet as parquet

        output = io.BytesIO()
        parquet.write_table(
            arrow.table(
                {
                    "order_id": arrow.array([1, 2], type=arrow.int64()),
                    "amount": arrow.array([10.5, 20.0], type=arrow.float64()),
                    "active": arrow.array([True, False], type=arrow.bool_()),
                }
            ),
            output,
        )
        config = validate_sync_config(
            default_sync_config(slug="orders", file_id="parquet-1"),
            expected_slug="orders",
        )

        tables = loader._extract_parquet(
            config,
            GoogleDriveFile(
                "parquet-1",
                "orders.parquet",
                "application/vnd.apache.parquet",
            ),
            output.getvalue(),
            set(),
        )

        types = {
            column["source_name"]: column["data_type"]
            for column in tables[0]["columns"]
        }
        self.assertEqual(
            {"order_id": "bigint", "amount": "double", "active": "bool"},
            types,
        )
        self.assertEqual(2, len(tables[0]["rows"]))


if __name__ == "__main__":
    unittest.main()
