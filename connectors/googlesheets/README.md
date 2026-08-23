# Connect Google Sheets

Settra uses Google OAuth to read spreadsheets on behalf of the connected Google
account. Each selected tab is fully synchronized into a durable table in the
dedicated PostgreSQL destination. Cube Core queries that stored snapshot rather
than making live Google API calls.

For direct Google Cloud Console links and the full click-by-click configuration,
see the [Google Cloud setup guide](../../GCP-SETUP.md).

## Configure the Google Cloud app

1. Create or select a Google Cloud project.
2. Enable the Google Sheets API, Google Drive API, and Google Picker API.
3. Configure the OAuth consent screen.
4. Add the recommended non-sensitive scope
   `https://www.googleapis.com/auth/drive.file`.
5. Create a **Web application** OAuth client.
6. Add the redirect URI shown on Settra's Data page. Locally it defaults to:

   `http://localhost:8000/api/google-oauth/callback`

7. Add `http://localhost:5173` as an authorized JavaScript origin for Vite.
8. Create an API key restricted to website requests from
   `http://localhost:5173/*` and restricted to the Google Picker API.
9. Set `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`,
   `GOOGLE_PICKER_API_KEY`, and `GOOGLE_PICKER_APP_ID` in Settra. The Picker app
   ID is the numeric project number, not the project name.

When Vite runs separately at `http://localhost:5173`, set
`SETTRA_FRONTEND_URL=http://localhost:5173`. Google still uses the backend
callback on port 8000; Settra redirects to the Vite Data page after exchanging
the authorization code.

Settra requests `drive.file`, which Google recommends for Picker. It authorizes
only spreadsheets the user explicitly selects rather than every readable file
in their Drive. The backend sends a short-lived access token to Picker and
retains only the encrypted refresh token.

## Connect and synchronize

1. Open **Data** and choose **Connect Google**.
2. Grant Settra access to files selected through the app.
3. Add a source and choose a spreadsheet with Google Picker. Picker supports
   folder navigation and Shared Drives.
4. Leave **Sheets** as `*`, or enter comma-separated tab names or wildcard
   patterns.
5. Save the source. Settra performs its first full load immediately.

The source's YAML contract controls table and column names, descriptions, type
overrides, and its cron schedule. A full load uses dlt's
`insert-from-staging` replacement strategy so readers continue seeing the
previous snapshot until the new load is ready.

## Sheet layout

- Put unique, non-empty column names in the first row.
- Avoid merged cells in the header row.
- Keep one record type per tab.
- Use type overrides in YAML when a value such as an identifier or business
  date must not rely on inference.

## Credential storage

The Google refresh token is encrypted with Settra's `SECRET_KEY`, written to the
data volume with owner-only permissions, and materialized as a dlt Google OAuth
credential only while a sync runs. It is not stored in SQLite or in source YAML.

Disconnecting Google prevents future loads but does not delete existing
PostgreSQL snapshots. Deleting a source also retains its PostgreSQL schema until
an administrator explicitly removes it.
