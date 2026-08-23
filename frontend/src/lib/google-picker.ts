import type { GooglePickerSession } from "@/lib/api";

export interface PickedGoogleSpreadsheet {
  id: string;
  name: string;
  url?: string;
}

declare global {
  interface Window {
    gapi?: any;
    google?: any;
  }
}

let pickerLibraryPromise: Promise<void> | null = null;

export async function openGoogleSpreadsheetPicker(
  session: GooglePickerSession,
): Promise<PickedGoogleSpreadsheet | null> {
  await loadPickerLibrary();

  return new Promise((resolve, reject) => {
    try {
      const pickerApi = window.google.picker;
      const myDriveView = new pickerApi.DocsView(
        pickerApi.ViewId.SPREADSHEETS,
      )
        .setIncludeFolders(true)
        .setSelectFolderEnabled(false)
        .setOwnedByMe(true)
        .setMode(pickerApi.DocsViewMode.LIST)
        .setLabel("My Drive");
      const sharedWithMeView = new pickerApi.DocsView(
        pickerApi.ViewId.SPREADSHEETS,
      )
        .setIncludeFolders(true)
        .setSelectFolderEnabled(false)
        .setOwnedByMe(false)
        .setMode(pickerApi.DocsViewMode.LIST)
        .setLabel("Shared with me");
      const sharedDrivesView = new pickerApi.DocsView(
        pickerApi.ViewId.SPREADSHEETS,
      )
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
        .setTitle("Choose a Google spreadsheet")
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
            reject(new Error("Google Picker returned no spreadsheet"));
            return;
          }

          resolve({
            id: document[pickerApi.Document.ID],
            name: document[pickerApi.Document.NAME] ?? "Google spreadsheet",
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
