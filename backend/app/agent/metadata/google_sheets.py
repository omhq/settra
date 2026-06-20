import json
import time
import logging

from typing import Any

from app.agent.metadata.utils import base64url, quote_ident

import httpx
import asyncpg

logger = logging.getLogger(__name__)


async def add_google_sheets_worksheet_tables(
    pg: asyncpg.Connection,
    schema: str,
    tables: dict[str, dict[str, Any]],
    *,
    connection_credentials: dict[str, str] | None = None,
) -> None:
    if "googlesheets_sheet" not in tables or "googlesheets_cell" not in tables:
        return

    direct_sheets = await _google_sheets_direct_header_rows(connection_credentials)

    if direct_sheets is not None:
        _add_google_sheets_tables_from_headers(
            tables,
            direct_sheets,
            header_source="google_sheets_api",
        )
        return

    sheet_rows = await pg.fetch(f"""
        SELECT title
        FROM {quote_ident(schema)}.googlesheets_sheet
        WHERE title IS NOT NULL
          AND title <> ''
        ORDER BY index, title
        """)

    for sheet_row in sheet_rows:
        sheet_name = str(sheet_row["title"] or "").strip()

        if not sheet_name or sheet_name.startswith("googlesheets_"):
            continue

        header_rows = await pg.fetch(
            f"""
            SELECT col, value
            FROM {quote_ident(schema)}.googlesheets_cell
            WHERE sheet_name = $1
              AND row = 1
              AND value IS NOT NULL
              AND value <> ''
            ORDER BY col
            """,
            sheet_name,
        )
        columns = _google_sheet_header_columns(header_rows)

        if not columns:
            continue

        _upsert_google_sheets_virtual_table(
            tables,
            sheet_name,
            columns,
            header_source="steampipe_googlesheets_cell",
        )


def google_sheets_virtual_table_context_lines(
    metadata: dict[str, Any],
    schema: str,
) -> list[str]:
    if not metadata.get("virtual") or metadata.get("source") != "googlesheets_cell":
        return []

    sheet_name = str(metadata.get("sheet_name") or "")
    header_row = metadata.get("header_row") or 1
    column_letters = metadata.get("column_letters")
    mapping = ""

    if isinstance(column_letters, dict) and column_letters:
        pairs = [
            f"{letter}->{name}"
            for name, letter in column_letters.items()
            if name and letter
        ]
        mapping = "; ".join(pairs[:24])

    notes = [
        (
            "Google Sheets virtual worksheet table: this table is synced from "
            f"{schema}.googlesheets_cell where sheet_name = {sheet_name!r}; "
            "it may not exist as a Steampipe relation."
        ),
        (
            "For SQL, reconstruct records from googlesheets_cell by grouping on "
            f"row > {header_row} and pivoting col values into the named fields."
        ),
    ]

    if mapping:
        notes.append(f"Header mapping: {mapping}.")

    return notes


def _add_google_sheets_tables_from_headers(
    tables: dict[str, dict[str, Any]],
    sheets: list[dict[str, Any]],
    *,
    header_source: str,
) -> None:
    for sheet in sheets:
        sheet_name = str(sheet.get("title") or "").strip()

        if not sheet_name or sheet_name.startswith("googlesheets_"):
            continue

        columns = _google_sheet_header_columns(sheet.get("headers") or [])

        if not columns:
            continue

        _upsert_google_sheets_virtual_table(
            tables,
            sheet_name,
            columns,
            header_source=header_source,
        )


def _upsert_google_sheets_virtual_table(
    tables: dict[str, dict[str, Any]],
    sheet_name: str,
    columns: list[dict[str, Any]],
    *,
    header_source: str,
) -> None:
    actual_table = tables.get(sheet_name)
    tables[sheet_name] = {
        "name": sheet_name,
        "description": (
            f"Worksheet data from Google Sheets tab {sheet_name}. "
            "Columns are synced from the current header row via "
            "googlesheets_cell."
        ),
        "columns": columns,
        "metadata": {
            "virtual": True,
            "source": "googlesheets_cell",
            "sheet_name": sheet_name,
            "header_row": 1,
            "actual_table_exists": bool(actual_table),
            "header_source": header_source,
            "column_letters": {
                str(column["name"]): str(column.get("source_column") or "")
                for column in columns
            },
        },
    }


def _google_sheet_header_columns(rows: list[Any]) -> list[dict[str, Any]]:
    seen: dict[str, int] = {}
    columns: list[dict[str, Any]] = []

    for row in rows:
        raw_name = str(row["value"] or "").strip()

        if not raw_name:
            continue

        count = seen.get(raw_name, 0) + 1
        seen[raw_name] = count
        column_name = raw_name if count == 1 else f"{raw_name}_{count}"

        columns.append(
            {
                "name": column_name,
                "type": "text",
                "nullable": True,
                "description": (
                    f"Google Sheets column {row['col']} from header row 1."
                ),
                "source_column": str(row["col"] or ""),
                "source_header": raw_name,
            }
        )

    return columns


async def _google_sheets_direct_header_rows(
    credentials: dict[str, str] | None,
) -> list[dict[str, Any]] | None:
    if not credentials:
        return None

    spreadsheet_id = str(credentials.get("spreadsheet_id") or "").strip()
    service_account_json = str(credentials.get("credentials") or "").strip()

    if not spreadsheet_id or not service_account_json:
        return None

    try:
        service_account = json.loads(service_account_json)

        if not isinstance(service_account, dict):
            return None

        async with httpx.AsyncClient(timeout=20) as client:
            token = await _google_sheets_service_account_token(
                client,
                service_account,
                str(credentials.get("impersonated_user_email") or "").strip(),
            )
            sheet_names = await _google_sheets_sheet_names(
                client,
                spreadsheet_id,
                token,
            )

            return await _google_sheets_header_values(
                client,
                spreadsheet_id,
                token,
                sheet_names,
            )
    except Exception as exc:
        logger.warning(
            "Direct Google Sheets header sync failed; falling back to "
            "Steampipe raw cells error=%s",
            exc,
        )
        return None


async def _google_sheets_service_account_token(
    client: httpx.AsyncClient,
    service_account: dict[str, Any],
    impersonated_user_email: str,
) -> str:
    client_email = str(service_account.get("client_email") or "").strip()
    private_key = str(service_account.get("private_key") or "").strip()

    if not client_email or not private_key:
        raise ValueError("Service account JSON is missing client_email/private_key")

    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": client_email,
        "scope": "https://www.googleapis.com/auth/spreadsheets.readonly",
        "aud": "https://oauth2.googleapis.com/token",
        "iat": now,
        "exp": now + 3600,
    }

    if (
        impersonated_user_email
        and impersonated_user_email.lower() != client_email.lower()
    ):
        claims["sub"] = impersonated_user_email

    assertion = _google_service_account_assertion(
        private_key,
        claims,
    )
    response = await client.post(
        "https://oauth2.googleapis.com/token",
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        },
    )

    response.raise_for_status()

    payload = response.json()
    token = str(payload.get("access_token") or "")

    if not token:
        raise ValueError("Google OAuth token response did not include access_token")

    return token


def _google_service_account_assertion(
    private_key_pem: str,
    claims: dict[str, Any],
) -> str:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    header = {"alg": "RS256", "typ": "JWT"}
    signing_input = (
        base64url(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + base64url(json.dumps(claims, separators=(",", ":")).encode())
    ).encode()
    key = serialization.load_pem_private_key(
        private_key_pem.encode(),
        password=None,
    )
    signature = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())

    return signing_input.decode() + "." + base64url(signature)


async def _google_sheets_sheet_names(
    client: httpx.AsyncClient,
    spreadsheet_id: str,
    token: str,
) -> list[str]:
    response = await client.get(
        f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}",
        headers={"Authorization": f"Bearer {token}"},
        params={"fields": "sheets(properties(title,index))"},
    )

    response.raise_for_status()

    payload = response.json()
    sheets = payload.get("sheets") if isinstance(payload, dict) else None

    if not isinstance(sheets, list):
        return []

    indexed_names = []

    for sheet in sheets:
        properties = sheet.get("properties") if isinstance(sheet, dict) else None

        if not isinstance(properties, dict):
            continue

        title = str(properties.get("title") or "").strip()

        if not title:
            continue

        indexed_names.append((int(properties.get("index") or 0), title))

    return [title for _, title in sorted(indexed_names)]


async def _google_sheets_header_values(
    client: httpx.AsyncClient,
    spreadsheet_id: str,
    token: str,
    sheet_names: list[str],
) -> list[dict[str, Any]]:
    if not sheet_names:
        return []

    params: list[tuple[str, str]] = [("majorDimension", "ROWS")]

    for sheet_name in sheet_names:
        params.append(("ranges", f"{_quote_sheet_name(sheet_name)}!1:1"))

    response = await client.get(
        f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values:batchGet",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
    )

    response.raise_for_status()

    payload = response.json()
    value_ranges = payload.get("valueRanges") if isinstance(payload, dict) else None

    if not isinstance(value_ranges, list):
        return []

    sheets = []

    for sheet_name, value_range in zip(sheet_names, value_ranges):
        values = value_range.get("values") if isinstance(value_range, dict) else None
        header_values = values[0] if values and isinstance(values[0], list) else []

        sheets.append(
            {
                "title": sheet_name,
                "headers": [
                    {
                        "col": _google_sheet_column_name(index + 1),
                        "value": value,
                    }
                    for index, value in enumerate(header_values)
                ],
            }
        )

    return sheets


def _quote_sheet_name(sheet_name: str) -> str:
    return "'" + sheet_name.replace("'", "''") + "'"


def _google_sheet_column_name(index: int) -> str:
    name = ""

    while index > 0:
        index, remainder = divmod(index - 1, 26)
        name = chr(ord("A") + remainder) + name

    return name
