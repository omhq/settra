# Contributing

Thanks for taking a look.

Settra is focused on making sheet data easier, safer, and more reliable for
automated agents. The current implementation supports Google Sheets as its only
source; contributions should strengthen that workflow rather than add another
application or data provider.

## Good first contributions

- Improve Google Sheets setup or troubleshooting documentation.
- Improve worksheet discovery, header handling, sampling, or type inference.
- Improve the bundled Google Sheets Cube model.
- Add realistic spreadsheet fixtures and agent query tests.
- Improve MCP compatibility, deployment instructions, or privacy safeguards.

## Pull request checklist

Before opening a PR, please check:

- The change keeps Google Sheets as the only supported source.
- Documentation is updated when behavior changes.
- Fixtures and examples contain no real spreadsheet IDs or credentials.
- Generated Cube models are reviewed before use with production data.
- Backend tests and the frontend build pass, or the PR explains why they were
  not run.

## Security issues

Do not open a public issue for security vulnerabilities. Report them privately
to the maintainers.
