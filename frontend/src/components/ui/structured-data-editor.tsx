import { forwardRef, lazy, Suspense } from "react";

import { cn } from "@/lib/utils";
import type {
  YamlEditorHandle,
  YamlEditorProps,
} from "@/components/ui/yaml-editor";

const MonacoStructuredDataEditor = lazy(() =>
  import("@/components/ui/yaml-editor").then((module) => ({
    default: module.YamlEditor,
  })),
);

export type StructuredDataEditorHandle = YamlEditorHandle;

export const StructuredDataEditor = forwardRef<
  StructuredDataEditorHandle,
  YamlEditorProps & { className?: string }
>(function StructuredDataEditor(
  { className, language = "yaml", ...props },
  ref,
) {
  return (
    <div
      className={cn(
        "h-[32rem] overflow-hidden rounded-lg border bg-background",
        className,
      )}
    >
      <Suspense
        fallback={
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            Loading {language.toUpperCase()} editor
          </div>
        }
      >
        <MonacoStructuredDataEditor ref={ref} language={language} {...props} />
      </Suspense>
    </div>
  );
});
