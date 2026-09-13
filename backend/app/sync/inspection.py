import codecs
import csv
import io
import re

from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Any, Iterable

GOOGLE_SHEETS_MIME_TYPE = "application/vnd.google-apps.spreadsheet"

CSV_MIME_TYPES = {
    "application/csv",
    "text/csv",
    "text/plain",
    "text/tab-separated-values",
}
EXCEL_MIME_TYPES = {
    "application/vnd.ms-excel",
    "application/vnd.ms-excel.sheet.macroenabled.12",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
PARQUET_MIME_TYPES = {
    "application/parquet",
    "application/vnd.apache.parquet",
    "application/x-parquet",
}
SUPPORTED_SOURCE_FORMATS = {"auto", "google_sheets", "csv", "excel", "parquet"}


@dataclass(frozen=True)
class GoogleDriveFile:
    file_id: str
    name: str
    mime_type: str
    size: int | None = None
    modified_time: str | None = None
    checksum: str | None = None
    can_download: bool = True


@dataclass
class TabularInspection:
    file: GoogleDriveFile
    format: str
    parsing: dict[str, Any] = field(default_factory=dict)
    header_rows: dict[str, int] = field(default_factory=dict)

    def manifest_source(self) -> dict[str, Any]:
        return {
            "file_name": self.file.name,
            "mime_type": self.file.mime_type,
            "format": self.format,
            **({"size": self.file.size} if self.file.size is not None else {}),
            **(
                {"modified_time": self.file.modified_time}
                if self.file.modified_time
                else {}
            ),
            **({"checksum": self.file.checksum} if self.file.checksum else {}),
            **({"parsing": self.parsing} if self.parsing else {}),
        }


class TabularFileInspector:
    """Infer a selected Drive file's tabular format and parsing settings."""

    SAMPLE_BYTES = 128 * 1024
    SAMPLE_ROWS = 100
    DELIMITERS = ",\t;|"

    def detect_format(
        self,
        file: GoogleDriveFile,
        *,
        configured: str = "auto",
        content: bytes | None = None,
    ) -> str:
        normalized = normalize_source_format(configured)

        if normalized != "auto":
            return normalized

        mime_type = file.mime_type.lower().split(";", 1)[0].strip()
        extension = PurePath(file.name.lower()).suffix

        if mime_type == GOOGLE_SHEETS_MIME_TYPE:
            return "google_sheets"
        if extension in {".parquet", ".pq"}:
            return "parquet"
        if extension in {".xlsx", ".xlsm", ".xls"}:
            return "excel"
        if extension in {".csv", ".tsv", ".txt"}:
            return "csv"
        if mime_type in PARQUET_MIME_TYPES:
            return "parquet"
        if mime_type in EXCEL_MIME_TYPES:
            return "excel"
        if mime_type in CSV_MIME_TYPES:
            return "csv"

        if content:
            if content.startswith(b"PAR1") and content[-4:] == b"PAR1":
                return "parquet"
            if content.startswith(b"PK\x03\x04") or content.startswith(
                b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
            ):
                return "excel"
            if mime_type not in {
                "",
                "application/octet-stream",
                "binary/octet-stream",
            }:
                raise ValueError(
                    f"Unsupported Google Drive file type: {file.mime_type or 'unknown'}"
                )
            try:
                encoding = self.detect_encoding(content)
                sample = content[: self.SAMPLE_BYTES].decode(encoding)

                if _is_probably_text(sample):
                    return "csv"
            except UnicodeError:
                pass

        raise ValueError(
            "Settra could not identify the selected file as Google Sheets, CSV, "
            "Excel, or Parquet. Set source.format explicitly in the sync YAML."
        )

    def inspect_delimited(
        self,
        content: bytes,
        *,
        file_name: str,
        parsing: dict[str, Any],
    ) -> tuple[str, str, list[list[str]], int]:
        configured_encoding = str(parsing.get("encoding") or "auto").strip()
        encoding = (
            self.detect_encoding(content)
            if configured_encoding.lower() == "auto"
            else configured_encoding
        )

        try:
            text = content.decode(encoding)
        except (LookupError, UnicodeDecodeError) as exc:
            raise ValueError(
                f"CSV could not be decoded with source.parsing.encoding={encoding!r}"
            ) from exc

        configured_delimiter = normalize_delimiter(parsing.get("delimiter", "auto"))
        delimiter = (
            self.detect_delimiter(text, file_name=file_name)
            if configured_delimiter == "auto"
            else configured_delimiter
        )
        rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter))
        header_row = resolve_header_row(parsing.get("header_row", "auto"), rows, self)
        return encoding, delimiter, rows, header_row

    def detect_encoding(self, content: bytes) -> str:
        sample = content[: self.SAMPLE_BYTES]

        if sample.startswith(codecs.BOM_UTF8):
            return "utf-8-sig"
        if sample.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
            return "utf-16"
        if sample.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
            return "utf-32"

        try:
            sample.decode("utf-8")
            return "utf-8"
        except UnicodeDecodeError:
            pass

        # cp1252 covers common Excel/Windows CSV exports. latin-1 is the final,
        # lossless single-byte fallback and can still be overridden in YAML.
        try:
            sample.decode("cp1252")
            return "cp1252"
        except UnicodeDecodeError:
            sample.decode("latin-1")
            return "latin-1"

    def detect_delimiter(self, text: str, *, file_name: str = "") -> str:
        sample = text[: self.SAMPLE_BYTES]

        try:
            return csv.Sniffer().sniff(sample, delimiters=self.DELIMITERS).delimiter
        except csv.Error:
            return "\t" if file_name.lower().endswith(".tsv") else ","

    def detect_header_row(self, rows: Iterable[Iterable[Any]]) -> int:
        sample = [list(row) for row in rows][: self.SAMPLE_ROWS]
        candidates: list[tuple[float, int]] = []

        for index, row in enumerate(sample):
            normalized = ["" if value is None else str(value).strip() for value in row]
            populated = [value for value in normalized if value]

            if not populated:
                continue

            width = max(
                (position + 1 for position, value in enumerate(normalized) if value),
                default=0,
            )
            following = [
                candidate
                for candidate in sample[index + 1 : index + 5]
                if any(value is not None and str(value).strip() for value in candidate)
            ]
            comparable_widths = [
                max(
                    (
                        position + 1
                        for position, value in enumerate(candidate)
                        if value is not None and str(value).strip()
                    ),
                    default=0,
                )
                for candidate in following
            ]
            width_matches = sum(
                1 for candidate_width in comparable_widths if candidate_width == width
            )
            textual = sum(1 for value in populated if not _looks_like_data(value))
            unique = len({value.casefold() for value in populated})
            score = (
                width_matches * 4 + textual * 2 + unique + min(width, 10) - index * 0.1
            )

            if comparable_widths and width == 1 and max(comparable_widths) > 1:
                score -= 8

            candidates.append((score, index + 1))

        if not candidates:
            raise ValueError("No usable header row was found")

        return max(candidates, key=lambda candidate: candidate[0])[1]


def normalize_source_format(value: Any) -> str:
    normalized = str(value or "auto").strip().lower().replace("-", "_")
    aliases = {
        "google_sheet": "google_sheets",
        "gsheet": "google_sheets",
        "sheets": "google_sheets",
        "xlsx": "excel",
        "xls": "excel",
        "xlsm": "excel",
        "pq": "parquet",
    }
    normalized = aliases.get(normalized, normalized)

    if normalized not in SUPPORTED_SOURCE_FORMATS:
        raise ValueError(
            "source.format must be one of: "
            + ", ".join(sorted(SUPPORTED_SOURCE_FORMATS))
        )

    return normalized


def normalize_delimiter(value: Any) -> str:
    normalized = str(value if value is not None else "auto")

    if normalized.lower() == "auto":
        return "auto"
    if normalized.lower() in {"tab", "\\t"}:
        return "\t"
    if normalized.lower() == "comma":
        return ","
    if normalized.lower() == "semicolon":
        return ";"
    if normalized.lower() == "pipe":
        return "|"
    if len(normalized) != 1:
        raise ValueError(
            "source.parsing.delimiter must be auto, tab, comma, semicolon, pipe, "
            "or one character"
        )

    return normalized


def resolve_header_row(
    value: Any,
    rows: Iterable[Iterable[Any]],
    inspector: TabularFileInspector,
) -> int:
    if isinstance(value, str) and value.strip().lower() == "auto":
        return inspector.detect_header_row(rows)

    if isinstance(value, bool):
        raise ValueError("header_row must be auto or a positive integer")

    try:
        resolved = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("header_row must be auto or a positive integer") from exc

    if resolved < 1:
        raise ValueError("header_row must be auto or a positive integer")

    return resolved


def display_delimiter(value: str) -> str:
    return "tab" if value == "\t" else value


def _looks_like_data(value: str) -> bool:
    normalized = value.strip()

    if not normalized:
        return False
    if re.fullmatch(r"[-+]?\d+(?:[.,]\d+)?", normalized):
        return True
    if normalized.casefold() in {"true", "false", "yes", "no", "null", "none"}:
        return True
    if re.fullmatch(r"\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}", normalized):
        return True

    return False


def _is_probably_text(value: str) -> bool:
    if not value or "\x00" in value:
        return False

    sample = value[:10000]
    readable = sum(
        character.isprintable() or character in "\r\n\t" for character in sample
    )
    return readable / len(sample) >= 0.9
