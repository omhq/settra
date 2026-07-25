import { useState } from "react";
import { CircleQuestionMark, LoaderCircle } from "lucide-react";

import { MarkdownContent } from "@/components/ui/markdown-content";
import { Button } from "@/components/ui/button";
import { useModal } from "@/components/ui/global-modal";
import { StateMessage } from "@/components/ui/state-message";
import { api, type Connector } from "@/lib/api";

const documentationCache = new Map<string, string>();

function ConnectorDocumentationButton({ connector }: { connector: Connector }) {
  const { openModal } = useModal();
  const [loading, setLoading] = useState(false);

  if (!connector.has_documentation) return null;

  async function openDocumentation() {
    setLoading(true);

    try {
      let content = documentationCache.get(connector.key);

      if (!content) {
        const documentation = await api.connectors.documentation(connector.key);
        content = documentation.content;
        documentationCache.set(connector.key, content);
      }

      const modalContent = content.replace(/^#\s+.+\r?\n+/, "");

      openModal({
        title: `${connector.name} setup guide`,
        body: (
          <MarkdownContent content={modalContent} className="text-foreground" />
        ),
        dialogClassName: "max-w-2xl",
        bodyClassName: "max-h-[70vh] overflow-y-auto pr-2",
      });
    } catch (error) {
      openModal({
        title: `${connector.name} setup guide`,
        body: (
          <StateMessage
            state="error"
            variant="inline"
            message={
              error instanceof Error
                ? error.message
                : "Could not load the setup guide."
            }
          />
        ),
      });
    } finally {
      setLoading(false);
    }
  }

  const label = `Open ${connector.name} setup guide`;

  return (
    <Button
      type="button"
      variant="ghost"
      size="icon-sm"
      className="size-6 text-muted-foreground hover:text-foreground"
      aria-label={label}
      title="Setup guide"
      disabled={loading}
      onClick={(event) => {
        event.stopPropagation();
        void openDocumentation();
      }}
    >
      {loading ? (
        <LoaderCircle className="size-3.5 animate-spin" />
      ) : (
        <CircleQuestionMark className="size-3.5" />
      )}
    </Button>
  );
}

export { ConnectorDocumentationButton };
