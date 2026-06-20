import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { ArrowUp, Info, Loader2, Plus } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  api,
  type ChatMessageRecord,
  type ChatQueryStep,
  type ChatResults,
  type ChatRun,
  type ChatStreamEvent,
  type ChatThread,
  type Connection,
  type ModelConfig,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ChatResultTable } from "@/components/chat-display/result-table/ChatResultTable";
import { ThreadList } from "@/components/chat-display/ThreadList";
import { DetailColumn } from "@/components/ui/detail-column";
import { MarkdownContent } from "@/components/ui/markdown-content";
import { SqlBlock } from "@/components/chat-display/SqlBlock";
import {
  MultiSelect,
  type MultiSelectOption,
} from "@/components/ui/multi-select";
import { useModal } from "@/components/ui/global-modal";
import { SelectMenu, type SelectMenuOption } from "@/components/ui/select-menu";
import { StatusBadge } from "@/components/ui/status-badge";
import { StateMessage } from "@/components/ui/state-message";
import { DateTime, type DateTimeValue } from "@/components/ui/datetime";
import { cn } from "@/lib/utils";

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  requestId?: string | null;
  createdAt?: string;
  sql?: string;
  results?: ChatResults;
  queryWorkspace?: ChatQueryStep[];
  queryAttempts?: number;
  maxQueryAttempts?: number;
  payload?: Record<string, unknown> | null;
  diagnostics?: Record<string, unknown> | null;
  pending?: boolean;
};

type ChatCommandNotice = {
  state: "info" | "success" | "warning";
  message: ReactNode;
};

const CHAT_COMMANDS = [
  {
    name: "clear",
    aliases: ["new", "reset"],
    usage: "/clear",
    description: "Clear this chat's stored history.",
  },
  {
    name: "help",
    aliases: [],
    usage: "/help",
    description: "Show available chat commands.",
  },
] as const;

function commandNames(command: (typeof CHAT_COMMANDS)[number]) {
  return [command.name, ...command.aliases];
}

function parseChatCommand(input: string) {
  if (!input.startsWith("/")) return null;

  const token = input.split(/\s+/, 1)[0].slice(1).toLowerCase();
  if (!token) return { name: null, token: "/" };

  const command = CHAT_COMMANDS.find((item) =>
    commandNames(item).some((name) => name === token),
  );

  return {
    name: command?.name ?? null,
    token: `/${token}`,
  };
}

function commandHelp() {
  return (
    <span>
      Available commands:{" "}
      {CHAT_COMMANDS.map((command) => (
        <span key={command.name}>
          <span className="font-medium">{command.usage}</span>
          {command.aliases.length > 0
            ? ` (${command.aliases.map((alias) => `/${alias}`).join(", ")})`
            : ""}
          {" - "}
          {command.description}
          {command.name === CHAT_COMMANDS[CHAT_COMMANDS.length - 1].name
            ? ""
            : "; "}
        </span>
      ))}
    </span>
  );
}

function QueryWorkspaceBlock({ steps }: { steps: ChatQueryStep[] }) {
  if (steps.length === 0) return null;

  return (
    <div className="mt-3 space-y-2">
      {steps.map((step) => {
        const results: ChatResults = {
          columns: step.columns,
          rows: step.rows,
          row_count: step.row_count,
          truncated: step.truncated,
        };

        return (
          <div key={`${step.attempt}-${step.name}`}>
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <span className="text-xs font-bold">
                {step.name || `Query ${step.attempt}`}
              </span>
              <Badge variant="secondary" className="text-[11px]">
                {step.attempt}/{step.max_attempts}
              </Badge>
              {step.error ? (
                <Badge variant="destructive" className="text-[11px]">
                  Failed
                </Badge>
              ) : (
                <Badge variant="outline" className="text-[11px]">
                  {step.row_count} rows
                </Badge>
              )}
            </div>
            {step.purpose && (
              <p className="mb-2 text-xs text-muted-foreground">
                {step.purpose}
              </p>
            )}
            {step.sql && <SqlBlock sql={step.sql} />}
            {step.error ? (
              <div className="mt-2">
                <StateMessage
                  state="error"
                  variant="inline"
                  message={step.error}
                />
              </div>
            ) : (
              <ChatResultTable results={results} />
            )}
          </div>
        );
      })}
    </div>
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function formatScalar(value: unknown) {
  if (value === null || value === undefined || value === "") return "none";
  if (Array.isArray(value))
    return `${value.length} item${value.length === 1 ? "" : "s"}`;
  if (typeof value === "object") return "object";
  return String(value);
}

function toDateTimeValue(value: unknown): DateTimeValue {
  if (
    typeof value === "string" ||
    typeof value === "number" ||
    value instanceof Date
  ) {
    return value;
  }

  return null;
}

function DetailRow({
  label,
  value,
  variant = "text",
}: {
  label: string;
  value: unknown;
  variant?: "text" | "datetime";
}) {
  return (
    <div className="grid grid-cols-[7rem_minmax(0,1fr)] gap-3 border-b py-2 last:border-b-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words text-xs text-foreground">
        {variant === "datetime" ? (
          <DateTime
            value={toDateTimeValue(value)}
            fallback="none"
            className="text-xs text-foreground"
          />
        ) : (
          formatScalar(value)
        )}
      </dd>
    </div>
  );
}

function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="max-h-80 overflow-auto rounded-md border bg-muted/20 p-3 text-[11px] leading-5 text-muted-foreground">
      {JSON.stringify(value ?? {}, null, 2)}
    </pre>
  );
}

function MessageDetails({ message }: { message: ChatMessage }) {
  const diagnostics = isRecord(message.diagnostics)
    ? message.diagnostics
    : isRecord(message.payload?.diagnostics)
      ? message.payload.diagnostics
      : null;
  const request = isRecord(diagnostics?.request) ? diagnostics.request : null;
  const timing = isRecord(diagnostics?.timing) ? diagnostics.timing : null;
  const tokenUsage = isRecord(diagnostics?.token_usage)
    ? diagnostics.token_usage
    : null;
  const steps = Array.isArray(diagnostics?.steps) ? diagnostics.steps : [];
  const llmCalls = Array.isArray(diagnostics?.llm_calls)
    ? diagnostics.llm_calls
    : [];

  return (
    <div className="space-y-5">
      <section>
        <h3 className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
          Message
        </h3>
        <dl>
          <DetailRow label="Role" value={message.role} />
          <DetailRow label="Message ID" value={message.id} />
          <DetailRow label="Request ID" value={message.requestId} />
          <DetailRow
            label="Created"
            value={message.createdAt}
            variant="datetime"
          />
        </dl>
      </section>

      {request && (
        <section>
          <h3 className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
            Request
          </h3>
          <dl>
            <DetailRow label="Thread" value={request.thread_id} />
            <DetailRow
              label="Model"
              value={isRecord(request.model) ? request.model.model : null}
            />
            <DetailRow
              label="Provider"
              value={isRecord(request.model) ? request.model.provider : null}
            />
            <DetailRow label="Connections" value={request.connection_ids} />
            <DetailRow label="Question chars" value={request.question_chars} />
          </dl>
        </section>
      )}

      {timing && (
        <section>
          <h3 className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
            Timing
          </h3>
          <dl>
            <DetailRow
              label="Started"
              value={timing.started_at ?? timing.created_at}
              variant="datetime"
            />
            <DetailRow
              label="Finished"
              value={timing.finished_at}
              variant="datetime"
            />
            <DetailRow label="Duration ms" value={timing.duration_ms} />
          </dl>
        </section>
      )}

      {tokenUsage && (
        <section>
          <h3 className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
            Tokens
          </h3>
          <dl>
            <DetailRow label="Input" value={tokenUsage.input_tokens} />
            <DetailRow label="Output" value={tokenUsage.output_tokens} />
            <DetailRow label="Total" value={tokenUsage.total_tokens} />
            <DetailRow label="Calls" value={tokenUsage.calls} />
            <DetailRow label="With usage" value={tokenUsage.calls_with_usage} />
          </dl>
        </section>
      )}

      {steps.length > 0 && (
        <section>
          <h3 className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
            Steps
          </h3>
          <div className="space-y-2">
            {steps.map((step, index) => {
              const item = isRecord(step) ? step : {};
              return (
                <div
                  key={`${item.node ?? "step"}-${index}`}
                  className="border-b pb-2 last:border-b-0"
                >
                  <div className="flex items-center justify-between gap-3 text-xs">
                    <span className="font-medium">
                      {formatScalar(item.label ?? item.node)}
                    </span>
                    <span className="text-muted-foreground">
                      {formatScalar(item.elapsed_ms)} ms
                    </span>
                  </div>
                  {item.error ? (
                    <p className="mt-1 text-xs text-destructive">
                      {formatScalar(item.error)}
                    </p>
                  ) : null}
                </div>
              );
            })}
          </div>
        </section>
      )}

      {llmCalls.length > 0 && (
        <section>
          <h3 className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
            LLM Calls
          </h3>
          <div className="space-y-2">
            {llmCalls.map((call, index) => {
              const item = isRecord(call) ? call : {};
              const usage = isRecord(item.token_usage) ? item.token_usage : {};
              return (
                <div
                  key={`${item.operation ?? "call"}-${index}`}
                  className="border-b pb-2 last:border-b-0"
                >
                  <div className="text-xs font-medium">
                    {formatScalar(item.operation)}
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {formatScalar(item.call_type)} | {formatScalar(item.status)}{" "}
                    | {formatScalar(item.duration_ms)} ms
                  </div>
                  {Object.keys(usage).length > 0 && (
                    <div className="mt-1 text-xs text-muted-foreground">
                      tokens {formatScalar(usage.total_tokens)} total
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      )}

      <section>
        <h3 className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
          Raw Diagnostics
        </h3>
        <JsonBlock value={diagnostics ?? { payload: message.payload }} />
      </section>
    </div>
  );
}

function MessageBubble({
  message,
  selected,
  onShowDetails,
}: {
  message: ChatMessage;
  selected: boolean;
  onShowDetails: (message: ChatMessage) => void;
}) {
  const isUser = message.role === "user";
  const hasWorkspace = Boolean(message.queryWorkspace?.length);
  const detailButton = (
    <button
      type="button"
      data-testid={`message-details-${message.id}`}
      title="Message details"
      aria-label="Message details"
      aria-pressed={selected}
      style={{ width: 24, minWidth: 24 }}
      className={cn(
        "inline-flex h-6 items-center justify-center rounded-md text-muted-foreground transition-colors hover:cursor-pointer hover:bg-muted hover:text-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none",
        selected && "bg-muted text-foreground",
      )}
      onPointerDown={(event) => {
        event.stopPropagation();
        onShowDetails(message);
      }}
      onClick={(event) => {
        event.stopPropagation();
        onShowDetails(message);
      }}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.stopPropagation();
          onShowDetails(message);
        }
      }}
    >
      <Info className="size-3.5" />
    </button>
  );

  return (
    <div
      className={cn(
        "flex w-full px-10",
        isUser ? "justify-end" : "justify-start",
      )}
    >
      <div
        className={cn("min-w-0", isUser ? "max-w-[min(42rem,85%)]" : "w-full")}
      >
        <div
          className={cn(
            "rounded-lg text-sm",
            isUser
              ? "px-3 py-2 bg-primary text-primary-foreground"
              : "bg-background text-foreground",
          )}
        >
          {isUser ? (
            <div className="whitespace-pre-wrap break-words">
              {message.content}
            </div>
          ) : (
            <MarkdownContent content={message.content} className="text-sm" />
          )}
          {message.pending && (
            <div className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
              <Loader2 className="size-3 animate-spin" />
              Working
            </div>
          )}
          {message.queryWorkspace && (
            <QueryWorkspaceBlock steps={message.queryWorkspace} />
          )}
          {!hasWorkspace && message.sql && <SqlBlock sql={message.sql} />}
          {!hasWorkspace && message.results && (
            <ChatResultTable results={message.results} />
          )}
          {!isUser && (
            <div className="mt-2 flex justify-start">{detailButton}</div>
          )}
        </div>
        {isUser && (
          <div className="mt-1/2 flex justify-end">{detailButton}</div>
        )}
      </div>
    </div>
  );
}

function toChatMessage(message: ChatMessageRecord): ChatMessage {
  return {
    id: String(message.id),
    role: message.role,
    content: message.content,
    requestId: message.request_id,
    createdAt: message.created_at,
    payload: message.payload as Record<string, unknown> | null,
    diagnostics: message.diagnostics ?? message.payload?.diagnostics ?? null,
    sql:
      typeof message.payload?.sql === "string"
        ? message.payload.sql
        : undefined,
    results: message.payload?.results,
    queryWorkspace: Array.isArray(message.payload?.query_workspace)
      ? message.payload.query_workspace
      : undefined,
    queryAttempts:
      typeof message.payload?.query_attempts === "number"
        ? message.payload.query_attempts
        : undefined,
    maxQueryAttempts:
      typeof message.payload?.max_query_attempts === "number"
        ? message.payload.max_query_attempts
        : undefined,
  };
}

export default function ChatPage() {
  const { openModal } = useModal();
  const location = useLocation();
  const navigate = useNavigate();
  const [connections, setConnections] = useState<Connection[]>([]);
  const [models, setModels] = useState<ModelConfig[]>([]);
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [activeThread, setActiveThread] = useState<ChatThread | null>(null);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [selectedModelId, setSelectedModelId] = useState<number | null>(null);
  const [threadId, setThreadId] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [selectedMessage, setSelectedMessage] = useState<ChatMessage | null>(
    null,
  );
  const [steps, setSteps] = useState<string[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadingThreadId, setLoadingThreadId] = useState<number | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [activeRun, setActiveRun] = useState<{
    requestId: string;
    threadId: number | null;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [commandNotice, setCommandNotice] = useState<ChatCommandNotice | null>(
    null,
  );
  const [messagesScrolled, setMessagesScrolled] = useState(false);
  const [composerHeight, setComposerHeight] = useState(0);
  const messagesRef = useRef<HTMLDivElement | null>(null);
  const composerRef = useRef<HTMLDivElement | null>(null);
  const submittingRef = useRef(false);
  const activeRunRequestRef = useRef<string | null>(null);
  const displayedThreadIdRef = useRef<number | null>(null);
  const suppressRequestedThreadLoadRef = useRef(false);
  const isChatsView = location.pathname.startsWith("/chat/chats");
  const requestedThreadId = useMemo(() => {
    const raw = new URLSearchParams(location.search).get("thread");

    if (!raw) return null;

    const parsed = Number(raw);
    return Number.isFinite(parsed) ? parsed : null;
  }, [location.search]);
  const shouldMeasureComposer =
    !loading && !isChatsView && connections.length > 0 && models.length > 0;

  function updateMessagesScrolled() {
    const nextScrolled = (messagesRef.current?.scrollTop ?? 0) > 0;

    setMessagesScrolled((current) =>
      current === nextScrolled ? current : nextScrolled,
    );
  }

  function scrollMessagesToBottom(behavior: ScrollBehavior = "auto") {
    const container = messagesRef.current;

    if (!container) return;

    container.scrollTo({
      top: container.scrollHeight,
      behavior,
    });
    updateMessagesScrolled();

    requestAnimationFrame(() => {
      container.scrollTo({
        top: container.scrollHeight,
        behavior,
      });
      updateMessagesScrolled();
    });
  }

  const resetChat = useCallback(
    (nextConnectionIds?: number[], nextModelId?: number) => {
      if (nextConnectionIds !== undefined) setSelectedIds(nextConnectionIds);
      if (nextModelId !== undefined) setSelectedModelId(nextModelId);
      setActiveThread(null);
      setThreadId(null);
      setMessages([]);
      setSelectedMessage(null);
      setSteps([]);
      setInput("");
      setError(null);
      setCommandNotice(null);

      if (location.pathname === "/chat" && requestedThreadId !== null) {
        suppressRequestedThreadLoadRef.current = true;
        navigate("/chat", { replace: true });
      }
    },
    [location.pathname, navigate, requestedThreadId],
  );

  useEffect(() => {
    Promise.all([
      api.connections.list(),
      api.models.list(),
      api.chat.threads.list(),
    ])
      .then(([items, modelItems, threadItems]) => {
        setConnections(items);
        setModels(modelItems);
        setThreads(threadItems);
        const firstActive =
          items.find((item) => item.status === "active") ?? items[0];
        if (firstActive) setSelectedIds([firstActive.id]);
        if (modelItems[0]) setSelectedModelId(modelItems[0].id);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  useLayoutEffect(() => {
    if (isChatsView) return;

    scrollMessagesToBottom("auto");
  }, [composerHeight, isChatsView, location.key, threadId, messages]);

  useLayoutEffect(() => {
    if (!shouldMeasureComposer) {
      setComposerHeight(0);
      return;
    }

    const composer = composerRef.current;

    if (!composer) return;

    const updateComposerHeight = () => {
      setComposerHeight(Math.ceil(composer.getBoundingClientRect().height));
    };
    const observer = new ResizeObserver(updateComposerHeight);

    updateComposerHeight();
    observer.observe(composer);

    return () => observer.disconnect();
  }, [shouldMeasureComposer]);

  useEffect(() => {
    displayedThreadIdRef.current = threadId;
  }, [threadId]);

  useEffect(() => {
    const handleNewChat = () => resetChat();

    window.addEventListener("settra:new-chat", handleNewChat);
    return () => window.removeEventListener("settra:new-chat", handleNewChat);
  }, [resetChat]);

  useEffect(() => {
    if (suppressRequestedThreadLoadRef.current) {
      if (requestedThreadId === null) {
        suppressRequestedThreadLoadRef.current = false;
      }
      return;
    }

    if (isChatsView || loading || requestedThreadId === null) return;
    if (loadingThreadId !== null) return;
    if (requestedThreadId === threadId) return;

    const requestedThread = threads.find(
      (thread) => thread.id === requestedThreadId,
    );
    if (!requestedThread) return;

    void loadThread(requestedThread);
  }, [
    isChatsView,
    loading,
    requestedThreadId,
    loadingThreadId,
    threadId,
    threads,
  ]);

  useEffect(() => {
    if (!selectedMessage) return;
    const freshMessage =
      messages.find((message) => message.id === selectedMessage.id) ?? null;

    if (freshMessage !== selectedMessage) {
      setSelectedMessage(freshMessage);
    }
  }, [messages, selectedMessage]);

  const selectedConnections = useMemo(
    () =>
      selectedIds
        .map((id) => connections.find((connection) => connection.id === id))
        .filter((connection): connection is Connection => Boolean(connection)),
    [connections, selectedIds],
  );

  const hasInactiveSelectedConnection = selectedConnections.some(
    (connection) => connection.status !== "active",
  );

  const connectionOptions = useMemo<MultiSelectOption[]>(
    () =>
      connections.map((connection) => ({
        value: String(connection.id),
        label: connection.name,
        description: connection.plugin,
        disabled: connection.status !== "active",
        meta: (
          <StatusBadge
            text={connection.status === "active" ? "Connected" : "Failed"}
            color={connection.status === "active" ? "green" : "red"}
          />
        ),
      })),
    [connections],
  );

  const selectedModel = useMemo(
    () => models.find((model) => model.id === selectedModelId) ?? null,
    [models, selectedModelId],
  );

  const modelOptions = useMemo<SelectMenuOption[]>(
    () =>
      models.map((model) => ({
        value: String(model.id),
        label: model.name,
        description: model.model,
        disabled: model.status !== "active",
        meta: (
          <StatusBadge
            text={model.status === "active" ? "Connected" : "Failed"}
            color={model.status === "active" ? "green" : "red"}
          />
        ),
      })),
    [models],
  );

  const trimmedInput = input.trim();
  const isCommandInput = trimmedInput.startsWith("/");
  const hasStartedThread = threadId !== null;
  const chatSubmitDisabled =
    (!hasStartedThread &&
      (selectedConnections.length === 0 ||
        hasInactiveSelectedConnection ||
        !selectedModel)) ||
    activeThread?.status === "inactive";
  const submitDisabled =
    streaming || !trimmedInput || (!isCommandInput && chatSubmitDisabled);
  const visibleStreaming =
    streaming &&
    (!activeRun?.threadId ||
      threadId === null ||
      activeRun.threadId === threadId);

  async function reloadThreads(nextActiveThreadId?: number | null) {
    const items = await api.chat.threads.list();
    setThreads(items);
    window.dispatchEvent(new Event("settra:threads-updated"));
    if (nextActiveThreadId) {
      setActiveThread(
        items.find((thread) => thread.id === nextActiveThreadId) ?? null,
      );
    }
  }

  async function loadThread(thread: ChatThread) {
    displayedThreadIdRef.current = thread.id;
    setLoadingThreadId(thread.id);
    setError(null);

    try {
      const detail = await api.chat.threads.get(thread.id);
      setActiveThread(detail.thread);
      setThreadId(detail.thread.id);
      setSelectedIds(
        detail.thread.connection_ids?.length
          ? detail.thread.connection_ids
          : [detail.thread.connection_id],
      );
      if (detail.thread.model_config_id) {
        setSelectedModelId(detail.thread.model_config_id);
      }
      const nextMessages = detail.messages.map(toChatMessage);
      const activeRun = detail.runs?.[0] ?? null;

      if (activeRun && !hasAssistantAfterRun(nextMessages, activeRun)) {
        nextMessages.push(pendingAssistantForRun(activeRun));
      }

      setMessages(nextMessages);
      setSelectedMessage(null);
      setSteps([]);
      setInput("");

      if (activeRun) {
        void followChatRun(
          activeRun,
          `pending-${activeRun.request_id}`,
          detail.thread.id,
        );
      }

      requestAnimationFrame(() => {
        scrollMessagesToBottom("auto");
        requestAnimationFrame(() => scrollMessagesToBottom("auto"));
      });
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoadingThreadId(null);
    }
  }

  async function deleteThread(thread: ChatThread) {
    setError(null);

    try {
      await api.chat.threads.delete(thread.id);
      setThreads((prev) => prev.filter((item) => item.id !== thread.id));
      window.dispatchEvent(new Event("settra:threads-updated"));
      if (thread.id === threadId) resetChat();
    } catch (err: any) {
      setError(err.message);
    }
  }

  function confirmDeleteThread(thread: ChatThread) {
    openModal({
      title: "Delete chat?",
      body: (
        <p>
          This permanently deletes{" "}
          <span className="font-medium text-foreground">{thread.title}</span>{" "}
          and its saved messages.
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
              void deleteThread(thread);
            }}
          >
            Delete chat
          </Button>
        </>
      ),
    });
  }

  async function clearCurrentChat() {
    const currentThreadId = threadId;

    setInput("");
    setError(null);

    if (currentThreadId !== null) {
      submittingRef.current = true;

      try {
        await api.chat.threads.clear(currentThreadId);
        setActiveThread((current) =>
          current?.id === currentThreadId
            ? { ...current, title: "New chat", last_message: null }
            : current,
        );
        await reloadThreads(currentThreadId);
      } catch (err: any) {
        setError(err.message);
        return;
      } finally {
        submittingRef.current = false;
      }
    } else {
      setActiveThread(null);
      setThreadId(null);
    }

    setSelectedMessage(null);
    setSteps([]);
    setMessages([]);
    setCommandNotice({
      state: "success",
      message:
        "Chat cleared. The next message will start from a clean history.",
    });
  }

  async function executeChatCommand(text: string) {
    const command = parseChatCommand(text);

    if (!command) return false;

    if (command.name === "clear") {
      await clearCurrentChat();
      return true;
    }

    if (command.name === "help") {
      setInput("");
      setError(null);
      setCommandNotice({ state: "info", message: commandHelp() });
      return true;
    }

    setCommandNotice({
      state: "warning",
      message: (
        <span>
          Unknown command <span className="font-medium">{command.token}</span>.
          Type <span className="font-medium">/help</span> for available
          commands.
        </span>
      ),
    });
    return true;
  }

  function pendingAssistantForRun(run: ChatRun): ChatMessage {
    return {
      id: `pending-${run.request_id}`,
      role: "assistant",
      content: "",
      requestId: run.request_id,
      createdAt: run.created_at,
      pending: true,
    };
  }

  function hasAssistantAfterRun(messages: ChatMessage[], run: ChatRun) {
    const userIndex = messages.findIndex(
      (message) => message.requestId === run.request_id,
    );

    if (userIndex === -1) return false;

    return messages
      .slice(userIndex + 1)
      .some((message) => message.role === "assistant");
  }

  function applyChatEvent(
    event: ChatStreamEvent,
    assistantId: string,
    options?: {
      ownerThreadId: number | null;
      onThread?: (threadId: number) => void;
    },
  ) {
    if (event.type === "thread") {
      options?.onThread?.(event.thread_id);
      displayedThreadIdRef.current = event.thread_id;
      setThreadId(event.thread_id);
      return;
    }

    const eventThreadId =
      "thread_id" in event && typeof event.thread_id === "number"
        ? event.thread_id
        : null;
    const ownerThreadId = eventThreadId ?? options?.ownerThreadId ?? null;
    const visible =
      ownerThreadId == null || displayedThreadIdRef.current === ownerThreadId;

    if (!visible) return;

    if (event.type === "step") {
      setSteps((prev) => [...prev, event.label]);
    }

    if (event.type === "result") {
      setMessages((prev) =>
        prev.map((message) =>
          message.id === assistantId
            ? {
                ...message,
                content: event.answer,
                sql: event.sql || undefined,
                results: event.results,
                queryWorkspace: event.query_workspace,
                queryAttempts: event.query_attempts,
                maxQueryAttempts: event.max_query_attempts,
                payload: event,
                diagnostics: event.diagnostics ?? null,
                pending: false,
              }
            : message,
        ),
      );
    }

    if (event.type === "error") {
      setMessages((prev) =>
        prev.map((message) =>
          message.id === assistantId
            ? {
                ...message,
                content: event.message,
                payload: event,
                diagnostics: event.diagnostics ?? null,
                pending: false,
              }
            : message,
        ),
      );
    }
  }

  async function followChatRun(
    run: ChatRun,
    assistantId: string,
    initialThreadId: number,
  ) {
    if (activeRunRequestRef.current === run.request_id) {
      return;
    }

    activeRunRequestRef.current = run.request_id;
    setActiveRun({ requestId: run.request_id, threadId: initialThreadId });
    setStreaming(true);
    setError(null);

    let currentThreadId = initialThreadId;
    let runThreadId: number | null = initialThreadId;

    try {
      await api.chat.events(run.request_id, (event) => {
        if (event.type === "thread") {
          runThreadId = event.thread_id;
          setActiveRun((current) =>
            current?.requestId === run.request_id
              ? { ...current, threadId: event.thread_id }
              : current,
          );
        }

        applyChatEvent(event, assistantId, {
          ownerThreadId: runThreadId,
          onThread: (nextThreadId) => {
            currentThreadId = nextThreadId;
          },
        });
      });
    } catch (err: any) {
      if (displayedThreadIdRef.current === runThreadId) {
        setError(err.message ?? "Chat stream failed");
        setMessages((prev) =>
          prev.map((message) =>
            message.id === assistantId
              ? {
                  ...message,
                  content: err.message ?? "Chat stream failed",
                  pending: false,
                }
              : message,
          ),
        );
      }
    } finally {
      if (activeRunRequestRef.current === run.request_id) {
        activeRunRequestRef.current = null;
        setActiveRun(null);
        setStreaming(false);
      }
      try {
        await reloadThreads(
          displayedThreadIdRef.current === currentThreadId
            ? currentThreadId
            : null,
        );
      } catch (err: any) {
        setError(err.message);
      }
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const text = input.trim();

    if (!text || streaming || submittingRef.current) {
      return;
    }

    if (await executeChatCommand(text)) {
      return;
    }

    const currentThreadInactive = activeThread?.status === "inactive";
    const isExistingThread = threadId !== null;
    if (
      (!isExistingThread &&
        (selectedConnections.length === 0 ||
          hasInactiveSelectedConnection ||
          !selectedModel)) ||
      currentThreadInactive ||
      !input.trim()
    ) {
      return;
    }

    const requestId = crypto.randomUUID();
    const submittedAt = new Date().toISOString();
    const assistantId = crypto.randomUUID();
    let currentThreadId = threadId;
    let runThreadId = threadId;
    submittingRef.current = true;
    activeRunRequestRef.current = requestId;
    setActiveRun({ requestId, threadId });
    setInput("");
    setError(null);
    setCommandNotice(null);
    setSteps([]);
    setStreaming(true);
    setMessages((prev) => [
      ...prev,
      {
        id: crypto.randomUUID(),
        role: "user",
        content: text,
        requestId,
        createdAt: submittedAt,
        diagnostics: {
          status: "submitted",
          request: {
            request_id: requestId,
            thread_id: threadId,
            question_chars: text.length,
            connection_ids: selectedConnections.map(
              (connection) => connection.id,
            ),
            connections: selectedConnections.map((connection) => ({
              id: connection.id,
              name: connection.name,
              schema: connection.slug,
              plugin: connection.plugin,
              status: connection.status,
            })),
            model: selectedModel
              ? {
                  id: selectedModel.id,
                  name: selectedModel.name,
                  provider: selectedModel.provider,
                  model: selectedModel.model,
                }
              : null,
          },
          timing: { created_at: submittedAt },
        },
      },
      {
        id: assistantId,
        role: "assistant",
        content: "",
        createdAt: submittedAt,
        pending: true,
      },
    ]);

    try {
      const chatBody = {
        message: text,
        thread_id: threadId,
        request_id: requestId,
        ...(isExistingThread
          ? {}
          : {
              connection_id: selectedConnections[0].id,
              connection_ids: selectedConnections.map(
                (connection) => connection.id,
              ),
              model_config_id: selectedModel?.id,
            }),
      };

      await api.chat.stream(chatBody, (event) => {
        if (event.type === "thread") {
          currentThreadId = event.thread_id;
          runThreadId = event.thread_id;
          setActiveRun((current) =>
            current?.requestId === requestId
              ? { ...current, threadId: event.thread_id }
              : current,
          );
        }

        applyChatEvent(event, assistantId, {
          ownerThreadId: runThreadId,
          onThread: (nextThreadId) => {
            currentThreadId = nextThreadId;
          },
        });
      });
    } catch (err: any) {
      const message = err.message ?? "Chat request failed";
      if (displayedThreadIdRef.current === runThreadId) {
        setError(message);
        setMessages((prev) =>
          prev.map((item) =>
            item.id === assistantId
              ? { ...item, content: message, pending: false }
              : item,
          ),
        );
      }
    } finally {
      submittingRef.current = false;
      if (activeRunRequestRef.current === requestId) {
        activeRunRequestRef.current = null;
        setActiveRun(null);
        setStreaming(false);
      }
      try {
        await reloadThreads(
          displayedThreadIdRef.current === currentThreadId
            ? currentThreadId
            : null,
        );
      } catch (err: any) {
        setError(err.message);
      }
    }
  }

  if (loading)
    return (
      <div className="p-6">
        <StateMessage state="loading" variant="banner" message="Loading chat" />
      </div>
    );
  if (error && connections.length === 0)
    return (
      <div className="p-6">
        <StateMessage state="error" variant="banner" message={error} />
      </div>
    );

  if (connections.length === 0 && !isChatsView) {
    return (
      <div className="p-4 sm:p-6">
        <StateMessage
          state="empty"
          variant="panel"
          title="No connections yet"
          message="Add a connection before starting a chat."
          action={
            <Button to="/connections/new" variant="primary">
              <Plus className="size-3" />
              Add connection
            </Button>
          }
        />
      </div>
    );
  }

  if (models.length === 0 && !isChatsView) {
    return (
      <div className="p-4 sm:p-6">
        <StateMessage
          state="empty"
          variant="panel"
          title="No models configured"
          message="Add a model before starting a chat."
          action={
            <Button to="/models/new" variant="primary">
              <Plus className="size-3" />
              Add model
            </Button>
          }
        />
      </div>
    );
  }

  if (isChatsView) {
    return (
      <div className="flex h-full min-h-0 flex-col overflow-hidden p-4 sm:p-6">
        <h1 className="mb-4 text-lg font-semibold">Chats</h1>
        <div className="min-h-0 flex-1 overflow-y-auto pr-1">
          <ThreadList
            threads={threads}
            loadingThreadId={loadingThreadId}
            onOpen={(thread) => navigate(`/chat?thread=${thread.id}`)}
            onDelete={confirmDeleteThread}
            className="space-y-2"
          />
        </div>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "grid h-full min-h-0 transition-[grid-template-columns] duration-200",
        selectedMessage
          ? "grid-cols-[minmax(0,1fr)_minmax(19rem,24rem)]"
          : "grid-cols-[minmax(0,1fr)]",
      )}
    >
      <div className="relative z-10 flex min-h-0 min-w-0 flex-col overflow-hidden bg-background">
        <div
          className={cn(
            "relative z-20 flex shrink-0 flex-col gap-3 bg-background px-4 pb-3 pt-4 transition-shadow sm:flex-row sm:items-center sm:justify-between",
            messagesScrolled && "border-b",
          )}
        >
          <div className="flex min-w-0 flex-wrap items-center gap-3 py-2">
            {selectedConnections.length > 0 && (
              <StatusBadge
                text={
                  hasInactiveSelectedConnection
                    ? "Connection failed"
                    : selectedConnections.length === 1
                      ? "Connected"
                      : `${selectedConnections.length} connected`
                }
                color={hasInactiveSelectedConnection ? "red" : "green"}
                title="Selected connections status"
              />
            )}
          </div>
          <div className="flex w-full min-w-0 flex-col gap-2 sm:w-auto sm:flex-row sm:items-center">
            <MultiSelect
              value={selectedIds.map(String)}
              options={connectionOptions}
              placeholder="Select connections"
              disabled={Boolean(threadId) || streaming}
              className="w-full sm:w-72"
              onChange={(value) => resetChat(value.map(Number))}
            />
            <SelectMenu
              value={selectedModelId ? String(selectedModelId) : null}
              options={modelOptions}
              placeholder="Select model"
              disabled={Boolean(threadId) || streaming}
              className="w-full sm:w-60"
              onChange={(value) => resetChat(undefined, Number(value))}
            />
          </div>
        </div>

        <div className="relative flex min-h-0 flex-1 flex-col gap-4 overflow-hidden">
          {selectedConnections.length === 0 && (
            <StateMessage
              state="warning"
              variant="banner"
              message="Select at least one connection to start a chat."
            />
          )}

          {hasInactiveSelectedConnection && (
            <StateMessage
              state="error"
              variant="banner"
              message="One or more selected connections are not active."
            />
          )}

          {activeThread?.status === "inactive" && (
            <StateMessage
              state="warning"
              variant="banner"
              message={`This chat is inactive${
                activeThread.inactive_reason
                  ? `: ${activeThread.inactive_reason}`
                  : ""
              }.`}
            />
          )}

          {commandNotice && (
            <StateMessage
              state={commandNotice.state}
              variant="banner"
              message={commandNotice.message}
            />
          )}

          <div className="flex min-h-0 flex-1 flex-col">
            <div
              ref={messagesRef}
              className="min-h-0 flex-1 space-y-2 overflow-y-auto"
              style={{
                paddingBottom: composerHeight
                  ? `${composerHeight + 8}px`
                  : undefined,
              }}
              onScroll={updateMessagesScrolled}
            >
              {messages.length === 0 && (
                <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                  Start with a question
                </div>
              )}
              {messages.map((message) => (
                <MessageBubble
                  key={message.id}
                  message={message}
                  selected={message.id === selectedMessage?.id}
                  onShowDetails={(nextMessage) =>
                    setSelectedMessage(nextMessage)
                  }
                />
              ))}
            </div>
          </div>

          <div
            ref={composerRef}
            className="pointer-events-none absolute inset-x-0 bottom-0 z-30 px-8 pb-4 pt-10"
          >
            {visibleStreaming && (
              <div className="mb-2 rounded-lg border bg-background/90 px-3 py-2 shadow-sm backdrop-blur">
                <div className="flex flex-wrap gap-1.5">
                  {steps.length > 0 ? (
                    steps.slice(-4).map((step, index) => (
                      <Badge key={`${step}-${index}`} variant="secondary">
                        {step}
                      </Badge>
                    ))
                  ) : (
                    <Badge variant="secondary">Starting chat run</Badge>
                  )}
                </div>
              </div>
            )}

            <form
              onSubmit={handleSubmit}
              className="pointer-events-auto relative"
            >
              <textarea
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    event.currentTarget.form?.requestSubmit();
                  }
                }}
                placeholder="Ask anything"
                rows={3}
                className="max-h-40 min-h-24 w-full resize-none rounded-2xl border border-input bg-background/95 px-4 py-3 pb-14 pr-14 text-sm shadow-[0_10px_24px_-18px_rgba(15,23,42,0.55)] outline-none backdrop-blur placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:shadow-[0_14px_30px_-18px_rgba(15,23,42,0.6)] disabled:cursor-not-allowed disabled:opacity-50"
                disabled={streaming}
              />
              <Button
                type="submit"
                size="icon-lg"
                title="Send"
                aria-label="Send message"
                className="absolute bottom-4 right-3 rounded-full shadow-sm"
                disabled={submitDisabled}
              >
                {visibleStreaming ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <ArrowUp className="size-4" />
                )}
              </Button>
            </form>
          </div>
        </div>
      </div>

      {selectedMessage && (
        <DetailColumn
          title="Message details"
          subtitle={
            <span className="capitalize">
              {selectedMessage.role} message
              {selectedMessage.createdAt ? " | " : ""}
              {selectedMessage.createdAt ? (
                <DateTime value={selectedMessage.createdAt} />
              ) : null}
            </span>
          }
          onClose={() => setSelectedMessage(null)}
        >
          <MessageDetails message={selectedMessage} />
        </DetailColumn>
      )}
    </div>
  );
}
