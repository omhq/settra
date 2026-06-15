import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Loader2, Plus } from "lucide-react";
import { api, type ModelConfig } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useModal } from "@/components/ui/global-modal";
import { ItemCard, ItemGrid } from "@/components/ui/item-grid";
import { RowActions } from "@/components/ui/row-actions";
import { StateMessage } from "@/components/ui/state-message";
import { StatusBadge } from "@/components/ui/status-badge";
import { Timestamp } from "@/components/ui/timestamp";

export default function ModelsPage() {
  const navigate = useNavigate();
  const { openModal } = useModal();
  const [models, setModels] = useState<ModelConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [testingId, setTestingId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    api.models
      .list()
      .then(setModels)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  async function deleteModel(model: ModelConfig) {
    setError(null);
    setWarning(null);
    setNotice(null);
    try {
      await api.models.delete(model.id);
      setModels((prev) => prev.filter((item) => item.id !== model.id));
      setNotice("Model deleted");
    } catch (err: any) {
      setWarning(err.message);
    }
  }

  function confirmDelete(model: ModelConfig) {
    openModal({
      title: "Delete model?",
      body: (
        <p>
          This deletes{" "}
          <span className="font-medium text-foreground">{model.name}</span>.
          Models can only be deleted after chats that use them are deleted.
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
              void deleteModel(model);
            }}
          >
            Delete model
          </Button>
        </>
      ),
    });
  }

  async function handleTest(model: ModelConfig) {
    setTestingId(model.id);
    setError(null);
    setWarning(null);
    setNotice(null);
    try {
      await api.models.test(model.id);
      setNotice(`${model.name} responded`);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setTestingId(null);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Models</h1>
        </div>
        <Button to="/models/new" variant="primary">
          <Plus className="size-3" />
        </Button>
      </div>

      {loading && (
        <StateMessage
          state="loading"
          variant="banner"
          message="Loading models"
        />
      )}
      {error && <StateMessage state="error" variant="banner" message={error} />}
      {warning && (
        <StateMessage state="warning" variant="banner" message={warning} />
      )}
      {notice && (
        <StateMessage state="success" variant="banner" message={notice} />
      )}

      {!loading && !error && models.length === 0 && (
        <StateMessage
          state="empty"
          variant="panel"
          title="No models configured"
          message="Add a model before starting chats or running AI introspection."
          action={
            <Button to="/models/new" variant="primary">
              <Plus className="size-3" />
              Add model
            </Button>
          }
        />
      )}

      {!loading && !error && models.length > 0 && (
        <ItemGrid>
          {models.map((model) => (
            <ItemCard
              key={model.id}
              title={model.name}
              pills={
                <>
                  <StatusBadge
                    text={model.status === "active" ? "Connected" : "Failed"}
                    color={model.status === "active" ? "green" : "red"}
                  />
                  <Badge variant="secondary">{model.provider}</Badge>
                </>
              }
              footer={
                <RowActions
                  actions={[
                    {
                      key: "test",
                      title: "Test",
                      ariaLabel: "Test model",
                      disabled: testingId === model.id,
                      icon:
                        testingId === model.id ? (
                          <Loader2 className="size-4 animate-spin" />
                        ) : undefined,
                      onClick: () => handleTest(model),
                    },
                    {
                      key: "edit",
                      title: "Edit",
                      ariaLabel: "Edit model",
                      onClick: () => navigate(`/models/${model.id}/edit`),
                    },
                    {
                      key: "delete",
                      title: "Delete",
                      ariaLabel: "Delete model",
                      onClick: () => confirmDelete(model),
                    },
                  ]}
                />
              }
            >
              <div className="space-y-2">
                <p className="break-words text-foreground">{model.model}</p>
                <p>
                  Created <Timestamp value={model.created_at} />
                </p>
              </div>
            </ItemCard>
          ))}
        </ItemGrid>
      )}
    </div>
  );
}
