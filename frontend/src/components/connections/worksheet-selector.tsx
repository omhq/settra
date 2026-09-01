import { Loader2 } from "lucide-react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { MultiSelect } from "@/components/ui/multi-select";
import type {
  ConnectionCredentialValue,
  GoogleDriveWorksheetDiscovery,
  SheetField,
} from "@/lib/api";

export function WorksheetSelector({
  field,
  fileSelected,
  discovery,
  loading,
  value,
  onChange,
  showLabel = true,
}: {
  field: SheetField;
  fileSelected: boolean;
  discovery: GoogleDriveWorksheetDiscovery | null;
  loading: boolean;
  value: ConnectionCredentialValue | undefined;
  onChange: (value: ConnectionCredentialValue) => void;
  showLabel?: boolean;
}) {
  if (!fileSelected) {
    return (
      <div className="space-y-1.5">
        {showLabel && <Label>{field.label}</Label>}
        <MultiSelect
          options={[]}
          value={[]}
          onChange={() => undefined}
          placeholder="Choose a Drive file first"
          disabled
          triggerClassName="h-9"
        />
        <p className="text-xs text-muted-foreground">
          Worksheet choices load after you select a Google Sheet or Excel file.
        </p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="space-y-1.5">
        {showLabel && <Label>{field.label}</Label>}
        <div className="flex h-9 items-center gap-2 rounded-md border border-input bg-muted/20 px-3 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" />
          Loading worksheets…
        </div>
      </div>
    );
  }

  if (discovery && !isWorkbook(discovery)) {
    return (
      <div className="rounded-md border border-border bg-muted/20 p-3 text-sm text-muted-foreground">
        {discovery.format === "csv" ? "CSV" : "Parquet"} files contain one
        table, so no worksheet selection is needed.
      </div>
    );
  }

  if (discovery && isWorkbook(discovery)) {
    const selected = selectedSheets(value);
    const discovered = new Set(discovery.worksheets);
    const configuredMissing = selected.filter(
      (name) => name !== "*" && !discovered.has(name),
    );
    const options = [
      {
        value: "*",
        label: "All worksheets",
        description: "Include every current and future worksheet",
      },
      ...discovery.worksheets.map((name) => ({ value: name, label: name })),
      ...configuredMissing.map((name) => ({
        value: name,
        label: name,
        description: "Configured, but not currently found in this file",
      })),
    ];

    return (
      <div className="space-y-1.5">
        {showLabel && <Label>{field.label}</Label>}
        <MultiSelect
          options={options}
          value={selected}
          onChange={(next) => {
            if (next.length === 0) {
              onChange(["*"]);
              return;
            }

            const added = next.find((name) => !selected.includes(name));
            onChange(
              added === "*" ? ["*"] : next.filter((name) => name !== "*"),
            );
          }}
          placeholder="Select worksheets"
          triggerClassName="h-9"
        />
        <p className="text-xs text-muted-foreground">
          Select one or more exact worksheet names, or keep All worksheets to
          preserve the wildcard behavior.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-1.5">
      {showLabel && <Label htmlFor={field.key}>{field.label}</Label>}
      <Input
        id={field.key}
        type="text"
        placeholder={field.placeholder}
        value={credentialText(value)}
        onChange={(event) => onChange(event.target.value)}
      />
      <p className="text-xs text-muted-foreground">
        Worksheet discovery was unavailable. Enter exact names or wildcard
        patterns separated by commas.
      </p>
    </div>
  );
}

export function credentialText(value: ConnectionCredentialValue | undefined) {
  return Array.isArray(value) ? value.join(", ") : String(value ?? "");
}

function selectedSheets(value: ConnectionCredentialValue | undefined) {
  if (Array.isArray(value)) return value.length > 0 ? value : ["*"];

  const parsed = String(value ?? "*")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  return parsed.length > 0 ? parsed : ["*"];
}

function isWorkbook(discovery: GoogleDriveWorksheetDiscovery) {
  return discovery.format === "google_sheets" || discovery.format === "excel";
}
