import { KeyRound } from "lucide-react";

import { MultiSelect } from "@/components/ui/multi-select";
import type {
  ConnectionCredentialValue,
  GoogleDriveWorksheetDiscovery,
  RowKeyDefinition,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function RowKeyEditor({
  discovery,
  selectedWorksheets,
  value,
  onChange,
}: {
  discovery: GoogleDriveWorksheetDiscovery | null;
  selectedWorksheets: ConnectionCredentialValue | undefined;
  value: Record<string, RowKeyDefinition>;
  onChange: (value: Record<string, RowKeyDefinition>) => void;
}) {
  if (discovery?.format !== "google_sheets") return null;

  const schemas = selectedSchemas(discovery, selectedWorksheets);

  return (
    <div className="space-y-3 rounded-md border border-border bg-muted/20 p-4">
      <div className="flex items-start gap-2.5">
        <KeyRound className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
        <div>
          <p className="text-sm font-medium text-foreground">Row identity</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Choose the column—or ordered combination of columns—that uniquely
            identifies a row. This will be required before an agent can update
            existing rows. Settra keeps composite values separate and can also
            expose an optional formatted ID with your preferred prefix or
            separators. Select up to eight columns.
          </p>
        </div>
      </div>

      {schemas.length === 0 ? (
        <p className="text-xs text-amber-700 dark:text-amber-300">
          Header discovery is unavailable for the selected worksheets. You can
          configure row keys later in the pipe’s Sync YAML.
        </p>
      ) : (
        <div className="space-y-3">
          {schemas.map((schema) => {
            const definition = value[schema.name];
            const columns = definition?.columns ?? [];
            const formatIssue = rowKeyFormatIssue(definition?.format, columns);

            return (
              <div key={schema.name} className="space-y-2">
                <div className="flex items-baseline justify-between gap-3">
                  <label className="truncate text-xs font-medium text-foreground">
                    {schema.name}
                  </label>
                  {schema.header_row && (
                    <span className="shrink-0 text-[11px] text-muted-foreground">
                      Header row {schema.header_row}
                    </span>
                  )}
                </div>
                {schema.columns.length > 0 || columns.length > 0 ? (
                  <>
                    <MultiSelect
                      options={rowKeyOptions(schema.columns, columns)}
                      value={columns}
                      onChange={(nextColumns) => {
                        if (nextColumns.length <= 8) {
                          onChange(
                            withRowKeyColumns(value, schema.name, nextColumns),
                          );
                        }
                      }}
                      placeholder="Select unique key columns"
                      triggerClassName="h-9"
                    />
                    {missingRowKeyColumns(schema.columns, columns).length >
                      0 && (
                      <p className="text-[11px] text-amber-700 dark:text-amber-300">
                        A configured key column is no longer present in the
                        discovered header. Remove it or restore the Sheet column
                        before syncing.
                      </p>
                    )}
                    {schema.columns_truncated && (
                      <p className="text-[11px] text-amber-700 dark:text-amber-300">
                        Only the first 100 columns were inspected. Use Sync YAML
                        if the key is farther right.
                      </p>
                    )}
                    {columns.length > 0 && (
                      <div className="space-y-1.5 rounded-md bg-background/60 p-3">
                        <div className="flex items-baseline justify-between gap-3">
                          <label
                            htmlFor={`row-key-format-${schema.name}`}
                            className="text-xs font-medium text-foreground"
                          >
                            Formatted identifier
                            <span className="ml-1 font-normal text-muted-foreground">
                              Optional
                            </span>
                          </label>
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            className="h-auto px-1.5 py-0.5 text-[11px]"
                            onClick={() =>
                              onChange(
                                withRowKeyFormat(
                                  value,
                                  schema.name,
                                  suggestedFormat(columns),
                                ),
                              )
                            }
                          >
                            Use suggested
                          </Button>
                        </div>
                        <Input
                          id={`row-key-format-${schema.name}`}
                          value={definition?.format ?? ""}
                          onChange={(event) =>
                            onChange(
                              withRowKeyFormat(
                                value,
                                schema.name,
                                event.target.value,
                              ),
                            )
                          }
                          placeholder={suggestedFormat(columns)}
                          maxLength={512}
                          className="h-9 font-mono text-xs"
                        />
                        <p
                          className={`text-[11px] ${
                            formatIssue
                              ? "text-destructive"
                              : "text-muted-foreground"
                          }`}
                        >
                          {formatIssue ?? (
                            <>
                              Use placeholders such as
                              <span className="font-mono">
                                {` {${columns[0]}}`}
                              </span>
                              , plus prefixes or separators. The rendered value
                              must also be unique.
                            </>
                          )}
                        </p>
                      </div>
                    )}
                  </>
                ) : (
                  <p className="text-xs text-amber-700 dark:text-amber-300">
                    {schema.error ?? "No usable header columns were found."}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      )}

      {discovery.worksheet_schema_truncated && (
        <p className="text-[11px] text-amber-700 dark:text-amber-300">
          Header discovery is limited to the first 20 worksheets. Additional row
          keys can be configured later in Sync YAML.
        </p>
      )}
      <p className="text-[11px] text-muted-foreground">
        If the Sheet already has a generated identifier such as
        <span className="font-mono"> ACME-2026-1042</span>, select that one
        column instead. A format is an agent-facing alias; Settra still uses the
        original column values as the authoritative identity.
      </p>
    </div>
  );
}

function selectedSchemas(
  discovery: GoogleDriveWorksheetDiscovery,
  selectedWorksheets: ConnectionCredentialValue | undefined,
) {
  const selected = worksheetNames(selectedWorksheets);
  const schemas = discovery.worksheet_schemas ?? [];

  if (selected.includes("*")) return schemas;

  const selectedSet = new Set(selected);
  return schemas.filter((schema) => selectedSet.has(schema.name));
}

function worksheetNames(value: ConnectionCredentialValue | undefined) {
  if (Array.isArray(value)) return value.length > 0 ? value : ["*"];

  const names = String(value ?? "*")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  return names.length > 0 ? names : ["*"];
}

function withRowKeyColumns(
  current: Record<string, RowKeyDefinition>,
  worksheet: string,
  columns: string[],
) {
  const next = { ...current };

  if (columns.length > 0) {
    next[worksheet] = {
      columns,
      ...(current[worksheet]?.format
        ? { format: current[worksheet].format }
        : {}),
    };
  } else delete next[worksheet];

  return next;
}

function withRowKeyFormat(
  current: Record<string, RowKeyDefinition>,
  worksheet: string,
  format: string,
) {
  const definition = current[worksheet];
  if (!definition) return current;

  return {
    ...current,
    [worksheet]: {
      columns: definition.columns,
      ...(format ? { format } : {}),
    },
  };
}

function rowKeyOptions(columns: string[], configured: string[]) {
  const discovered = new Set(columns);
  return [
    ...columns.map((column) => ({ value: column, label: column })),
    ...configured
      .filter((column) => !discovered.has(column))
      .map((column) => ({
        value: column,
        label: column,
        description: "Configured, but not currently found in the header",
      })),
  ];
}

function missingRowKeyColumns(columns: string[], configured: string[]) {
  const discovered = new Set(columns);
  return configured.filter((column) => !discovered.has(column));
}

function suggestedFormat(columns: string[]) {
  return columns.map((column) => `{${column}}`).join("-");
}

function rowKeyFormatIssue(format: string | undefined, columns: string[]) {
  if (!format) return null;
  if (!format.trim()) return "The formatted identifier cannot be blank.";
  if (format.length > 512) return "The format cannot exceed 512 characters.";

  const parsed = rowKeyFormatFields(format);
  if (parsed.error) return parsed.error;

  const unknown = parsed.fields.filter((field) => !columns.includes(field));
  if (unknown.length > 0) {
    return `Unknown row-key placeholder: ${unknown[0]}`;
  }

  const missing = columns.filter((column) => !parsed.fields.includes(column));
  if (missing.length > 0) {
    return `Include every selected column; missing: ${missing.join(", ")}`;
  }

  return null;
}

function rowKeyFormatFields(template: string): {
  fields: string[];
  error?: string;
} {
  const fields: string[] = [];

  for (let index = 0; index < template.length; index += 1) {
    if (template[index] === "{") {
      if (template[index + 1] === "{") {
        index += 1;
        continue;
      }

      const closing = template.indexOf("}", index + 1);
      if (closing < 0)
        return { fields, error: "The format has an unclosed brace." };

      const field = template.slice(index + 1, closing);
      if (!field) return { fields, error: "Placeholders cannot be empty." };
      if (field.includes("{")) {
        return {
          fields,
          error: "The format has nested opening braces.",
        };
      }

      fields.push(field);
      index = closing;
    } else if (template[index] === "}") {
      if (template[index + 1] === "}") {
        index += 1;
      } else {
        return { fields, error: "The format has an unmatched closing brace." };
      }
    }
  }

  return { fields };
}
