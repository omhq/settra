import { useState } from "react";
import { CircleQuestionMark, LoaderCircle } from "lucide-react";

import { MarkdownContent } from "@/components/ui/markdown-content";
import { Button } from "@/components/ui/button";
import { useModal } from "@/components/ui/global-modal";
import { StateMessage } from "@/components/ui/state-message";
import { api, type GoogleDriveConfig } from "@/lib/api";

let documentationCache: string | null = null;

function GoogleDriveDocumentationButton({
  config,
}: {
  config: GoogleDriveConfig;
}) {
  const { openModal } = useModal();
  const [loading, setLoading] = useState(false);

  if (!config.has_documentation) return null;

  async function openDocumentation() {
    setLoading(true);

    try {
      if (!documentationCache) {
        documentationCache = (await api.googleDrive.documentation()).content;
      }

      const modalContent = documentationCache.replace(/^#\s+.+\r?\n+/, "");

      openModal({
        title: "Google Drive source setup guide",
        body: (
          <MarkdownContent content={modalContent} className="text-foreground" />
        ),
        dialogClassName: "max-w-2xl",
        bodyClassName: "max-h-[70vh] overflow-y-auto pr-2",
      });
    } catch (error) {
      openModal({
        title: "Google Drive source setup guide",
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

  return (
    <Button
      type="button"
      variant="ghost"
      size="icon-sm"
      className="size-6 text-muted-foreground hover:text-foreground"
      aria-label="Open Google Drive source setup guide"
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

export { GoogleDriveDocumentationButton };
