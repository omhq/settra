# Connect Google Sheets

The simplest setup uses a Google service account. You will create a read-only identity, share one spreadsheet with it, and paste its JSON key into Settra.

You need:

- The Google Sheet you want to query.
- Permission to create or use a Google Cloud project.
- About five minutes.

## 1. Enable the Google APIs

In the Google Cloud console, select an existing project or create a new one. Then enable both:

- [Google Sheets API](https://console.cloud.google.com/apis/library/sheets.googleapis.com)
- [Google Drive API](https://console.cloud.google.com/apis/library/drive.googleapis.com)

## 2. Create a service account

Open [Create service account](https://console.cloud.google.com/iam-admin/serviceaccounts/create).

1. Name it something recognizable, such as `settra-sheets-reader`.
2. Click **Create and continue**.
3. You do not need to grant it a Google Cloud project role for this setup.
4. Click **Done**.

## 3. Download its JSON key

Open [Service accounts](https://console.cloud.google.com/iam-admin/serviceaccounts), then open the account you just created.

1. Select **Keys**.
2. Click **Add key**, then **Create new key**.
3. Choose **JSON** and click **Create**.

Google downloads a `.json` file. Keep it private: anyone with this file can act as the service account.

## 4. Share the spreadsheet

Open the downloaded JSON file and copy its `client_email`. It looks like:

```text
settra-sheets-reader@your-project.iam.gserviceaccount.com
```

Open your Google Sheet, click **Share**, and add that email as a **Viewer**. Viewer access is enough for Settra to query the sheet.

## 5. Fill in Settra

Create a Google Sheets connection and enter:

| Settra field         | What to enter                                                      |
| -------------------- | ------------------------------------------------------------------ |
| Connection name      | Any useful label, such as `Sales forecast`                         |
| Spreadsheet ID       | The text between `/d/` and `/edit` in the spreadsheet URL          |
| Sheets               | Leave `*` to include every tab, or enter comma-separated tab names |
| Service Account JSON | Paste the entire contents of the downloaded JSON file              |
| Principal Email      | Paste the same `client_email` from the JSON file                   |
| OAuth Token Path     | Leave blank                                                        |

For this URL:

```text
https://docs.google.com/spreadsheets/d/1AbC_example_ID/edit
```

the Spreadsheet ID is:

```text
1AbC_example_ID
```

Click **Save connection**. A brand-new service account or key can take about a minute to become usable; retry once if the first attempt fails.

## Make your sheet easy to query

- Put column names in the first row of each tab.
- Give every column a unique, non-empty name.
- Avoid merged cells in the header row.
- Keep one kind of record per tab.
- Use consistent date and number formats down each column.

## Troubleshooting

**Permission denied or spreadsheet not found**

- Confirm the spreadsheet is shared with the service account `client_email`, not your personal Gmail address.
- Confirm the Spreadsheet ID contains only the ID, not the full URL.
- Confirm both the Google Sheets API and Google Drive API are enabled in the same Cloud project as the service account.

**Your organization will not let you create a JSON key**

Some Google Workspace organizations block service account keys. Ask your Google Cloud administrator for an approved service-account key, or use the advanced OAuth Token Path option. That path must exist inside the Settra Steampipe container, so it requires deployment-specific setup.

**Tabs or columns are missing**

- Leave **Sheets** as `*`, or check that every listed tab name exactly matches Google Sheets.
- Make sure the first row contains the column names.
- Retry or refresh the connection after changing the sheet.

## Security

Treat the service account JSON like a password. Give the service account Viewer access unless you truly need more, do not commit the JSON to Git, and revoke the key in Google Cloud if it is ever exposed.

For additional configuration options, see the [Steampipe Google Sheets plugin documentation](https://hub.steampipe.io/plugins/turbot/googlesheets).
