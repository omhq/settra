# Contributing

Thanks for taking a look.

Settra is focused on making Google Drive tabular data easier, safer, and more
reliable for automated agents. The current implementation supports Google
Sheets, CSV, Excel, and Parquet from Google Drive; contributions should
strengthen that workflow rather than add another application or data provider.

## Good first contributions

- Improve Google Drive setup or troubleshooting documentation.
- Improve file inspection, worksheet discovery, header handling, or type inference.
- Improve generated Cube models and source metadata.
- Add realistic tabular-file fixtures and agent query tests.
- Improve MCP compatibility, deployment instructions, or privacy safeguards.

## Pull request checklist

Before opening a PR, run `make test` and check:

- The change keeps Google Drive as the source provider.
- Documentation is updated when behavior changes.
- Fixtures and examples contain no real Drive file IDs or credentials.
- Generated Cube models are reviewed before use with production data.
- Backend tests and the frontend build pass, or the PR explains why they were
  not run.

## Security issues

Do not open a public issue for security vulnerabilities. Report them privately
to the maintainers.
