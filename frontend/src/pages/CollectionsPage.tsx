import { useEffect, useState } from "react";
import { Copy, FolderTree, Plus } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { DataTabs } from "@/components/data/data-tabs";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useModal } from "@/components/ui/global-modal";
import { ItemCard, ItemGrid } from "@/components/ui/item-grid";
import { RowActions } from "@/components/ui/row-actions";
import { StateMessage } from "@/components/ui/state-message";
import { api, type DataCollection, type DeploymentSettings } from "@/lib/api";

export default function CollectionsPage() {
  const navigate = useNavigate();
  const { openModal } = useModal();
  const [collections, setCollections] = useState<DataCollection[]>([]);
  const [settings, setSettings] = useState<DeploymentSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);

  async function load() {
    setError(null);
    try {
      const [nextCollections, nextSettings] = await Promise.all([
        api.collections.list(),
        api.settings.get(),
      ]);
      setCollections(nextCollections);
      setSettings(nextSettings);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function copyMcpUrl(collection: DataCollection) {
    const base = settings?.public_url || window.location.origin;
    const url = `${base.replace(/\/$/, "")}${collection.mcp_path}`;

    try {
      await navigator.clipboard.writeText(url);
      setNotice(`Copied the ${collection.name} MCP URL.`);
    } catch {
      setError(`Could not copy the MCP URL. Use ${url}`);
    }
  }

  function confirmDelete(collection: DataCollection) {
    openModal({
      title: "Delete collection?",
      body: (
        <p>
          This removes {collection.name} as an agent workspace. Its pipes,
          PostgreSQL snapshots, and Cube models are retained.
        </p>
      ),
      actions: ({ close }) => (
        <>
          <Button type="button" variant="outline" onClick={close}>
            Cancel
          </Button>
          <Button
            type="button"
            variant="destructive"
            onClick={() => {
              close();
              void removeCollection(collection);
            }}
          >
            Delete collection
          </Button>
        </>
      ),
    });
  }

  async function removeCollection(collection: DataCollection) {
    try {
      await api.collections.delete(collection.id);
      setCollections((current) =>
        current.filter((item) => item.id !== collection.id),
      );
      setNotice(`${collection.name} deleted. Its data was retained.`);
    } catch (err: any) {
      setError(err.message);
    }
  }

  return (
    <div className="space-y-7">
      <DataTabs
        action={
          <Button to="/data/collections/new" variant="primary">
            <Plus className="size-3.5" /> New collection
          </Button>
        }
      />

      {loading && (
        <StateMessage
          state="loading"
          variant="banner"
          message="Loading collections"
        />
      )}
      {error && (
        <StateMessage
          state="error"
          variant="banner"
          message={error}
          onClose={() => setError(null)}
        />
      )}
      {notice && (
        <StateMessage
          state="success"
          variant="banner"
          message={notice}
          onClose={() => setNotice(null)}
        />
      )}

      {!loading && collections.length === 0 ? (
        <StateMessage
          state="empty"
          variant="panel"
          title="No collections"
          message="Create a collection to give agents a focused set of related pipes and cubes."
          action={
            <Button to="/data/collections/new" variant="primary">
              <Plus className="size-3.5" /> New collection
            </Button>
          }
        />
      ) : (
        !loading && (
          <ItemGrid>
            {collections.map((collection) => {
              const isExpanded = expanded === collection.id;

              return (
                <ItemCard
                  key={collection.id}
                  title={collection.name}
                  pills={
                    <>
                      <Badge variant="outline">
                        {collection.pipe_count} pipes
                      </Badge>
                      <Badge variant="outline">
                        {collection.table_count} tables
                      </Badge>
                    </>
                  }
                  footer={
                    <>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => void copyMcpUrl(collection)}
                      >
                        <Copy className="size-3.5" /> MCP URL
                      </Button>
                      <RowActions
                        actions={[
                          {
                            key: "view",
                            title: isExpanded ? "Hide pipes" : "View pipes",
                            onClick: () =>
                              setExpanded(isExpanded ? null : collection.id),
                          },
                          {
                            key: "edit",
                            title: "Edit collection",
                            onClick: () =>
                              navigate(
                                `/data/collections/${collection.id}/edit`,
                              ),
                          },
                          {
                            key: "delete",
                            title: "Delete collection",
                            onClick: () => confirmDelete(collection),
                          },
                        ]}
                      />
                    </>
                  }
                  footerClassName="justify-between"
                >
                  <div className="space-y-3">
                    <p>
                      {collection.description ||
                        "No collection description has been added."}
                    </p>

                    {collection.agent_instructions && (
                      <div className="rounded-lg border bg-muted/25 p-3">
                        <p className="text-xs font-medium uppercase tracking-wide text-foreground">
                          Agent instructions
                        </p>
                        <p className="mt-1 whitespace-pre-wrap">
                          {collection.agent_instructions}
                        </p>
                      </div>
                    )}

                    {isExpanded && (
                      <div className="space-y-2 border-t pt-3">
                        {collection.pipes.length === 0 ? (
                          <p>This collection has no pipes yet.</p>
                        ) : (
                          collection.pipes.map((pipe) => (
                            <div
                              key={pipe.id}
                              className="flex items-start gap-2 rounded-lg border px-3 py-2"
                            >
                              <FolderTree className="mt-0.5 size-3.5 shrink-0" />
                              <div className="min-w-0">
                                <p className="truncate text-foreground">
                                  {pipe.name}
                                </p>
                                <p className="font-mono text-xs">
                                  {pipe.destination_name ?? "Destination"} /{" "}
                                  {pipe.destination_schema} · {pipe.table_count}{" "}
                                  tables
                                </p>
                              </div>
                            </div>
                          ))
                        )}
                      </div>
                    )}
                  </div>
                </ItemCard>
              );
            })}
          </ItemGrid>
        )
      )}
    </div>
  );
}
