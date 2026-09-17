import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StateMessage } from "@/components/ui/state-message";
import { api, type TableSample, type TableProfile } from "@/lib/api";

export function TableInspector({
  collectionId,
  pipeId,
  table,
}: {
  collectionId: number;
  pipeId: number;
  table: string;
}) {
  const [sample, setSample] = useState<TableSample | null>(null);
  const [profile, setProfile] = useState<TableProfile | null>(null);
  const [columns, setColumns] = useState("");
  const [limit, setLimit] = useState(5);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  async function inspect(kind: "sample" | "profile") {
    setBusy(true);
    setError(null);
    try {
      const selected = columns
        .split(",")
        .map((column) => column.trim())
        .filter(Boolean);
      if (selected.length > 24)
        throw new Error("Choose up to 24 columns at a time.");
      if (kind === "sample") {
        setSample(
          await api.collections.sampleTable(
            collectionId,
            pipeId,
            table,
            limit,
            selected.length ? selected : undefined,
          ),
        );
        setProfile(null);
      } else {
        setProfile(
          await api.collections.profileTable(
            collectionId,
            pipeId,
            table,
            500,
            selected.length ? selected : undefined,
          ),
        );
        setSample(null);
      }
      setStale(false);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }
  const display = (value: unknown) =>
    value === null || value === undefined
      ? "—"
      : typeof value === "object"
        ? JSON.stringify(value)
        : String(value);
  return (
    <div className="space-y-3 p-3">
      <label className="block space-y-1 text-xs">
        <span>
          Columns (comma-separated, up to 24; blank uses the first 24)
        </span>
        <Input
          disabled={busy}
          value={columns}
          onChange={(event) => {
            setColumns(event.target.value);
            setStale(true);
          }}
          placeholder="order_id, customer_id"
        />
      </label>
      <div className="flex flex-wrap items-end gap-2">
        <label className="block space-y-1 text-xs">
          <span>Sample rows</span>
          <Input
            className="w-20"
            type="number"
            min={1}
            max={50}
            disabled={busy}
            value={limit}
            onChange={(event) => {
              setLimit(Number(event.target.value));
              setStale(true);
            }}
          />
        </label>
        <Button
          variant="outline"
          size="sm"
          disabled={busy || limit < 1 || limit > 50}
          onClick={() => void inspect("sample")}
        >
          Sample rows
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={busy}
          onClick={() => void inspect("profile")}
        >
          Profile keys
        </Button>
      </div>
      {error && <StateMessage state="error" variant="banner" message={error} />}
      {stale && (sample || profile) && (
        <p className="text-xs text-muted-foreground">
          Inputs changed. Inspect again to refresh these results.
        </p>
      )}
      {sample && (
        <>
          <p className="text-xs text-muted-foreground">
            {sample.rows.length} sampled rows
            {sample.truncated_values?.length
              ? ` · Truncated values: ${sample.truncated_values.join(", ")}`
              : ""}
          </p>
          <div className="max-h-80 overflow-auto rounded-md border">
            <table className="w-full text-left text-xs">
              <thead>
                <tr>
                  {sample.columns.map((column) => (
                    <th key={column} className="whitespace-nowrap px-2 py-1">
                      {column}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sample.rows.map((row, index) => (
                  <tr key={index} className="border-t">
                    {row.map((value, index) => (
                      <td key={index} className="whitespace-nowrap px-2 py-1">
                        {display(value)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {profile && (
        <>
          <p className="text-xs text-muted-foreground">
            Profile of {profile.sampled_rows} sampled rows (up to 500). Sample
            uniqueness does not prove whole-table uniqueness.
          </p>
          <div className="max-h-80 overflow-auto rounded-md border">
            <table className="w-full text-left text-xs">
              <thead>
                <tr>
                  {["Column", "Type", "Nulls", "Distinct", "Examples"].map(
                    (label) => (
                      <th key={label} className="whitespace-nowrap px-2 py-1">
                        {label}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody>
                {Object.entries(profile.columns).map(([name, column]) => (
                  <tr key={name} className="border-t">
                    <td className="px-2 py-1">{name}</td>
                    <td className="px-2 py-1">
                      {column.type ||
                        column.inferred_type ||
                        column.source_type}
                    </td>
                    <td className="px-2 py-1">{column.nulls}</td>
                    <td className="px-2 py-1">{column.distinct}</td>
                    <td className="px-2 py-1">
                      {column.examples?.map(display).join(", ")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
