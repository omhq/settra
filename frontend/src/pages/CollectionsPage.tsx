import { useEffect, useState } from "react";
import { Copy, Plus } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ItemCard, ItemGrid } from "@/components/ui/item-grid";
import { RowActions } from "@/components/ui/row-actions";
import { StateMessage } from "@/components/ui/state-message";
import { Tooltip } from "@/components/ui/tooltip";
import { api, type DataCollection, type DeploymentSettings } from "@/lib/api";

export default function CollectionsPage() {
  const navigate = useNavigate();
  const [collections, setCollections] = useState<DataCollection[]>([]);
  const [settings, setSettings] = useState<DeploymentSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

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

  return (
    <div className="space-y-7">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Apps</h1>
        <Tooltip content="New App">
          <Button
            to="/data/apps/new"
            variant="primary"
            size="icon"
            aria-label="New App"
          >
            <Plus />
          </Button>
        </Tooltip>
      </div>

      {loading && (
        <StateMessage state="loading" variant="banner" message="Loading Apps" />
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
          title="No Apps"
          message="Create an App to combine related sources, semantic models, calculations, inputs, and results."
          action={
            <Button to="/data/apps/new" variant="primary">
              <Plus className="size-3.5" /> New App
            </Button>
          }
        />
      ) : (
        !loading && (
          <ItemGrid>
            {collections.map((collection) => {
              return (
                <ItemCard
                  key={collection.id}
                  title={
                    <Link
                      to={`/data/apps/${collection.id}`}
                      className="hover:text-primary hover:underline"
                    >
                      {collection.name}
                    </Link>
                  }
                  pills={
                    <>
                      <Badge variant="outline">
                        {collection.pipe_count} sources
                      </Badge>
                      <Badge variant="outline">
                        {collection.table_count} tables
                      </Badge>
                      <Badge variant="outline">
                        {collection.calculation_count} calculations
                      </Badge>
                    </>
                  }
                  footer={
                    <>
                      {settings?.deployment_mode === "self_hosted" && (
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() => void copyMcpUrl(collection)}
                        >
                          <Copy className="size-3.5" /> MCP URL
                        </Button>
                      )}
                      <RowActions
                        actions={[
                          {
                            key: "view",
                            title: "View App",
                            onClick: () =>
                              navigate(`/data/apps/${collection.id}`),
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
                        "No App description has been added."}
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
