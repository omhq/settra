import { Loader2, MessageSquare, Trash2 } from "lucide-react";

import { ActionMenu } from "@/components/ui/action-menu";
import { Timestamp } from "@/components/ui/timestamp";
import { type ChatThread } from "@/lib/api";
import { cn } from "@/lib/utils";

type ThreadListProps = {
  threads: ChatThread[];
  onOpen: (thread: ChatThread) => void;
  onDelete?: (thread: ChatThread) => void;
  activeThreadId?: number | null;
  loadingThreadId?: number | null;
  disabled?: boolean;
  maxItems?: number;
  className?: string;
  itemClassName?: string;
  showTimestamp?: boolean;
  emptyLabel?: string;
};

export function ThreadList({
  threads,
  onOpen,
  onDelete,
  activeThreadId,
  loadingThreadId,
  disabled = false,
  maxItems,
  className,
  itemClassName,
  showTimestamp = true,
  emptyLabel = "No chats yet.",
}: ThreadListProps) {
  const visibleThreads =
    typeof maxItems === "number" ? threads.slice(0, maxItems) : threads;

  if (visibleThreads.length === 0) {
    return (
      <div className="flex items-center gap-2 rounded-md py-2 text-sm text-muted-foreground">
        <MessageSquare className="size-4" />
        {emptyLabel}
      </div>
    );
  }

  return (
    <div className={cn("space-y-1", className)}>
      {visibleThreads.map((thread) => {
        const active = thread.id === activeThreadId;
        const rowDisabled = disabled || loadingThreadId != null;

        return (
          <div
            key={thread.id}
            className={cn(
              "group flex items-center rounded-md transition-colors hover:bg-muted/60",
              active && "bg-muted text-foreground",
              rowDisabled && "opacity-60",
              itemClassName,
            )}
          >
            <button
              type="button"
              title={thread.title}
              disabled={rowDisabled}
              onClick={() => onOpen(thread)}
              className="flex min-w-0 flex-1 cursor-pointer items-center gap-2 rounded-md px-2 py-2 text-left disabled:cursor-not-allowed"
            >
              <span className="flex min-w-0 flex-1 flex-col items-start">
                <span className="w-full truncate text-sm font-medium">
                  {thread.title}
                </span>
                {showTimestamp && (
                  <Timestamp
                    value={thread.updated_at}
                    className="mt-1 block w-full truncate"
                  />
                )}
              </span>
            </button>
            {onDelete ? (
              <ActionMenu
                label={`Actions for ${thread.title}`}
                disabled={rowDisabled}
                className="mr-1"
                actions={[
                  {
                    label: "Delete",
                    danger: true,
                    icon: <Trash2 className="size-4" />,
                    onSelect: () => onDelete(thread),
                  },
                ]}
              />
            ) : null}
            {loadingThreadId === thread.id ? (
              <Loader2 className="mr-2 size-3.5 animate-spin" />
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
