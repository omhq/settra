import type { GooglePickerSession } from "@/lib/api";

export interface PickedGoogleDriveFile {
  id: string;
  name: string;
  mimeType: string;
  url?: string;
}

declare global {
  interface Window {
    gapi?: any;
    google?: any;
  }
}

let pickerLibraryPromise: Promise<void> | null = null;

export async function openGoogleDriveFilePicker(
  session: GooglePickerSession,
): Promise<PickedGoogleDriveFile | null> {
  await loadPickerLibrary();

  return new Promise((resolve, reject) => {
    try {
      const pickerApi = window.google.picker;
      const myDriveView = new pickerApi.DocsView(pickerApi.ViewId.DOCS)
        .setIncludeFolders(true)
        .setSelectFolderEnabled(false)
        .setOwnedByMe(true)
        .setMode(pickerApi.DocsViewMode.LIST)
        .setLabel("My Drive");
      const sharedWithMeView = new pickerApi.DocsView(pickerApi.ViewId.DOCS)
        .setIncludeFolders(true)
        .setSelectFolderEnabled(false)
        .setOwnedByMe(false)
        .setMode(pickerApi.DocsViewMode.LIST)
        .setLabel("Shared with me");
      const sharedDrivesView = new pickerApi.DocsView(pickerApi.ViewId.DOCS)
        .setIncludeFolders(true)
        .setSelectFolderEnabled(false)
        .setEnableDrives(true)
        .setMode(pickerApi.DocsViewMode.LIST)
        .setLabel("Shared drives");
      const picker = new pickerApi.PickerBuilder()
        .setAppId(session.app_id)
        .setOAuthToken(session.access_token)
        .setDeveloperKey(session.api_key)
        .setOrigin(window.location.origin)
        .setTitle("Choose a Sheet, CSV, Excel, or Parquet file")
        .addView(myDriveView)
        .addView(sharedWithMeView)
        .addView(sharedDrivesView)
        .setCallback((data: Record<string, any>) => {
          if (data.action === pickerApi.Action.CANCEL) {
            resolve(null);
            return;
          }

          if (data.action !== pickerApi.Action.PICKED) {
            return;
          }

          const documents = data[pickerApi.Response.DOCUMENTS] ?? [];
          const document = documents[0];

          if (!document) {
            reject(new Error("Google Picker returned no Drive file"));
            return;
          }

          const name = document[pickerApi.Document.NAME] ?? "Google Drive file";
          const mimeType = document[pickerApi.Document.MIME_TYPE] ?? "";

          if (!isSupportedTabularFile(name, mimeType)) {
            reject(
              new Error(
                "Choose a Google Sheet, CSV, Excel (.xlsx, .xlsm, .xls), or Parquet file.",
              ),
            );
            return;
          }

          resolve({
            id: document[pickerApi.Document.ID],
            name,
            mimeType,
            url: document[pickerApi.Document.URL],
          });
        })
        .build();

      picker.setVisible(true);
    } catch (error) {
      reject(error);
    }
  });
}

function isSupportedTabularFile(name: string, mimeType: string): boolean {
  const normalizedName = name.toLowerCase();
  const normalizedMime = mimeType.toLowerCase().split(";", 1)[0];
  const supportedMimes = new Set([
    "application/csv",
    "application/parquet",
    "application/vnd.apache.parquet",
    "application/vnd.google-apps.spreadsheet",
    "application/vnd.ms-excel",
    "application/vnd.ms-excel.sheet.macroenabled.12",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/x-parquet",
    "text/csv",
    "text/tab-separated-values",
  ]);

  return (
    supportedMimes.has(normalizedMime) ||
    /\.(csv|tsv|xlsx|xlsm|xls|parquet|pq)$/i.test(normalizedName)
  );
}

function loadPickerLibrary(): Promise<void> {
  if (window.google?.picker) {
    return Promise.resolve();
  }

  if (pickerLibraryPromise) {
    return pickerLibraryPromise;
  }

  pickerLibraryPromise = new Promise((resolve, reject) => {
    const loadPicker = () => {
      if (!window.gapi) {
        reject(new Error("Google Picker library did not initialize"));
        return;
      }

      window.gapi.load("picker", {
        callback: resolve,
        onerror: () => reject(new Error("Google Picker could not be loaded")),
      });
    };

    const existing = document.querySelector<HTMLScriptElement>(
      'script[data-settra-google-picker="true"]',
    );

    if (existing) {
      if (window.gapi) {
        loadPicker();
      } else {
        existing.addEventListener("load", loadPicker, { once: true });
        existing.addEventListener(
          "error",
          () => reject(new Error("Google Picker script could not be loaded")),
          { once: true },
        );
      }
      return;
    }

    const script = document.createElement("script");
    script.src = "https://apis.google.com/js/api.js";
    script.async = true;
    script.defer = true;
    script.dataset.settraGooglePicker = "true";
    script.addEventListener("load", loadPicker, { once: true });
    script.addEventListener(
      "error",
      () => reject(new Error("Google Picker script could not be loaded")),
      { once: true },
    );
    document.head.appendChild(script);
  });

  return pickerLibraryPromise;
}
