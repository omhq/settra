import type { ReactNode } from "react";
import { ChevronDown } from "lucide-react";

import type { SemanticStatus } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { ItemCard, ItemGrid } from "@/components/ui/item-grid";
import { MarkdownContent } from "@/components/ui/markdown-content";
import { RowActions, type RowAction } from "@/components/ui/row-actions";
import { cn } from "@/lib/utils";

function SemanticSection({
  title,
  count,
  open,
  onToggle,
  children,
}: {
  title: string;
  count: number;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  const contentId = `semantic-section-${title
    .replace(/\W+/g, "-")
    .toLowerCase()}`;

  return (
    <section className="space-y-3">
      <h2>
        <button
          type="button"
          aria-expanded={open}
          aria-controls={contentId}
          title={`${open ? "Collapse" : "Expand"} ${title}`}
          className="inline-flex h-8 items-center gap-2 rounded-md px-1.5 text-base font-semibold transition-colors hover:bg-muted focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
          onClick={onToggle}
        >
          <ChevronDown
            className={cn(
              "size-4 text-muted-foreground transition-transform",
              !open && "-rotate-90",
            )}
          />
          <span>{title}</span>
          <Badge variant="secondary">{count}</Badge>
        </button>
      </h2>
      {open && (
        <ItemGrid id={contentId} className="gap-3">
          {children}
        </ItemGrid>
      )}
    </section>
  );
}

function SemanticBlock({
  title,
  status,
  hidden,
  meta,
  rows,
  actions,
}: {
  title: string;
  status: SemanticStatus;
  hidden?: boolean;
  meta?: ReactNode;
  rows: [string, ReactNode][];
  actions: ReactNode;
}) {
  return (
    <ItemCard
      title={title}
      pills={
        <>
          <SemanticStatusPill status={status} hidden={hidden} />
          {meta}
        </>
      }
      footer={actions}
      bodyClassName="text-foreground"
    >
      <dl className="grid gap-x-6 gap-y-2 text-sm">
        {rows.map(([label, value]) => {
          const content =
            label === "Evidence" && typeof value === "string" ? (
              <MarkdownContent content={value} className="text-sm" />
            ) : (
              value
            );

          return (
            <div key={label} className="min-w-0">
              <dt className="text-xs font-medium text-muted-foreground">
                {label}
              </dt>
              <dd className="mt-0.5 break-words text-foreground">{content}</dd>
            </div>
          );
        })}
      </dl>
    </ItemCard>
  );
}

function BlockActions({
  item,
  hidden,
  reviewLabel = "Approve",
  onReview,
  onApprove,
  onEdit,
  onReject,
  onHide,
  onDisable,
  onReset,
  onDelete,
  deleteLabel = "Delete",
}: {
  item: { status: SemanticStatus };
  hidden?: boolean;
  reviewLabel?: string;
  onReview?: () => void;
  onApprove: () => void;
  onEdit: () => void;
  onReject: () => void;
  onHide: () => void;
  onDisable: () => void;
  onReset: () => void;
  onDelete: () => void;
  deleteLabel?: string;
}) {
  if (isApprovedStatus(item.status) && !hidden) {
    return (
      <RowActions
        actions={[
          { key: "edit", title: "Edit", onClick: onEdit },
          { key: "disable", title: "Disable", onClick: onDisable },
          { key: "reset", title: "Reset to suggestion", onClick: onReset },
          { key: "delete", title: deleteLabel, onClick: onDelete },
        ]}
      />
    );
  }

  if (hidden || item.status === "disabled" || item.status === "ignored") {
    return (
      <RowActions
        actions={[
          { key: "edit", title: "Edit", onClick: onEdit },
          { key: "reset", title: "Reset to suggestion", onClick: onReset },
          { key: "delete", title: deleteLabel, onClick: onDelete },
        ]}
      />
    );
  }

  const reviewActions: RowAction[] = onReview
    ? [{ key: "review", title: "Review examples", onClick: onReview }]
    : [];

  return (
    <RowActions
      actions={[
        { key: "approve", title: reviewLabel, onClick: onApprove },
        ...reviewActions,
        { key: "edit", title: "Edit", onClick: onEdit },
        { key: "reject", title: "Reject", onClick: onReject },
        { key: "hide", title: "Hide", onClick: onHide },
        { key: "delete", title: deleteLabel, onClick: onDelete },
      ]}
    />
  );
}

function SemanticStatusPill({
  status,
  hidden,
}: {
  status: SemanticStatus;
  hidden?: boolean;
}) {
  if (hidden || status === "hidden") {
    return <Badge variant="outline">Hidden</Badge>;
  }

  if (isApprovedStatus(status)) {
    return <Badge variant="default">Approved</Badge>;
  }

  if (status === "ignored" || status === "disabled") {
    return <Badge variant="destructive">Ignored</Badge>;
  }

  return <Badge variant="secondary">Needs Review</Badge>;
}

function isApprovedStatus(status: SemanticStatus) {
  return status === "confirmed" || status === "published";
}

export { BlockActions, SemanticBlock, SemanticSection, isApprovedStatus };
