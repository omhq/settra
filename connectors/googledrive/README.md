# Connect Google Drive tabular files

The Google Drive connector makes selected Google Sheets, CSV, Excel, and
Parquet data durable and available to automated agents. Google Picker grants
file-specific access, dlt loads normalized tables into PostgreSQL, and Cube Core
serves governed semantics over the durable snapshots.

## Configure the Google Cloud app

1. Enable the Google Sheets API, Google Drive API, and Google Picker API.
2. Configure the OAuth consent screen with the non-sensitive
   `https://www.googleapis.com/auth/drive.file` scope.
3. Create a Web application OAuth client and configure Settra's callback URI.
4. Create a browser-restricted Google Picker API key.
5. Set `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`,
   `GOOGLE_PICKER_API_KEY`, and `GOOGLE_PICKER_APP_ID` in Settra.

Settra retains only the encrypted Google refresh token. File contents are read
during synchronization and are not stored in source YAML.

## Supported files

- Native Google Sheets: one synchronized table per selected tab.
- CSV and TSV: one table per file.
- Excel `.xlsx`, `.xlsm`, and `.xls`: one table per selected worksheet.
- Parquet: one table per file, preserving compatible column types.

Choose a file with Google Picker when creating a source. Picker supports My
Drive, files shared with the connected account, and Shared Drives. The same
Drive file ID is used by scheduled synchronization, so new revisions of that
file are loaded automatically. If an upload creates a different Drive file,
select the new file in the pipe editor.

## Automatic inspection and YAML overrides

On the first successful synchronization, Settra detects the file format. For
delimited files it also detects encoding, delimiter, and header row. Detected
values are written into the pipe's sync YAML. Set any value back to `auto` to
detect it again, or specify an override:

```yaml
version: 1
source:
  type: google_drive
  file_id: 1AbC_example
  file_name: orders.csv
  mime_type: text/csv
  format: csv
  sheets: ['*']
  parsing:
    encoding: utf-8-sig
    delimiter: comma
    header_row: 2
destination:
  key: built_in_postgres
  type: postgres
  schema: orders
load:
  write_disposition: replace
  replace_strategy: insert-from-staging
  schema_contract:
    tables: evolve
    columns: evolve
    data_type: evolve
  schedule:
    enabled: false
    cron: "0 * * * *"
    timezone: UTC
schema:
  tables: {}
```

Allowed formats are `auto`, `google_sheets`, `csv`, `excel`, and `parquet`.
Delimiter values can be `auto`, `comma`, `tab`, `semicolon`, `pipe`, or one
literal character. A table or worksheet may override the global header row:

```yaml
schema:
  tables:
    Forecast:
      header_row: 3
      table_name: forecast
      row_key:
        columns: [Account ID, Invoice Date]
        format: "INV-{Account ID}-{Invoice Date}"
```

`row_key.columns` is an ordered list of one or more source header names that
jointly identify a row. Every component must be populated and the combination
must be unique in a successful snapshot. An optional `row_key.format` creates a
readable external identifier using `{Source Header}` placeholders plus literal
prefixes or separators. It must reference every selected key column, and the
rendered identifiers must also be unique; for example, values containing the
separator cannot silently collapse two distinct tuples into one ID. Use `{{`
and `}}` for literal braces. Settra keeps the separate source values as the
authoritative identity and never parses the formatted identifier back into its
components. If the source already contains a generated identifier such as
`ACME-2026-1042`, select that column alone and leave `format` unset unless a
prefix is useful. Row keys use this same contract for Google Sheets tabs, Excel
worksheets, and the single table in CSV or Parquet files.

The first usable header row defines source columns. Put unique column names in
that row and avoid merged header cells. Excel formula cells use the last cached
value saved in the workbook; Settra does not evaluate Excel formulas.

Each synchronization remains a complete replacement using dlt's
`insert-from-staging` strategy, so readers continue seeing the previous durable
snapshot until the new load is ready.

The destination `key` identifies a separately registered Settra destination.
Every current deployment seeds one `built_in_postgres` destination backed by
the deployment's `POSTGRES_*` environment variables. The UI shows it explicitly
as the default destination; credentials are never copied into pipe YAML or the
product database.
