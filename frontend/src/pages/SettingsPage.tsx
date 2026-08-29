import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  Check,
  ChevronDown,
  Copy,
  ExternalLink,
  MessageSquareText,
  PlugZap,
  Terminal,
} from "lucide-react";

import { api, type DeploymentSettings } from "@/lib/api";
import { useAuth } from "@/auth/auth-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SecretInput } from "@/components/ui/secret-input";
import { StateMessage } from "@/components/ui/state-message";
import { Tooltip } from "@/components/ui/tooltip";
import { productSlug } from "@/config/product";
import { cn } from "@/lib/utils";

export default function SettingsPage() {
  const auth = useAuth();
  const [settings, setSettings] = useState<DeploymentSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copyError, setCopyError] = useState<string | null>(null);
  const [copiedField, setCopiedField] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [workspaceName, setWorkspaceName] = useState("");
  const [savingWorkspace, setSavingWorkspace] = useState(false);

  useEffect(() => {
    api.settings
      .get()
      .then((value) => {
        setSettings(value);
        setWorkspaceName(value.organization.name);
      })
      .catch((err: unknown) =>
        setError(
          err instanceof Error ? err.message : "Could not load settings.",
        ),
      )
      .finally(() => setLoading(false));
  }, []);

  const mcpJson = useMemo(
    () =>
      settings
        ? JSON.stringify(
            {
              mcpServers: {
                [productSlug(settings.product_name)]: {
                  type: "streamable-http",
                  url: settings.mcp_url,
                },
              },
            },
            null,
            2,
          )
        : "",
    [settings],
  );

  const mcpServerName = settings
    ? productSlug(settings.product_name)
    : "settra";
  const codexAddCommand = settings
    ? `codex mcp add ${mcpServerName} --url ${settings.mcp_url} --oauth-resource ${settings.public_url} --oauth-client-registration dcr`
    : "";
  const codexLoginCommand = `codex mcp login ${mcpServerName} --scopes settra:read --oauth-client-registration dcr`;

  async function copyValue(field: string, value: string) {
    setCopyError(null);

    try {
      await navigator.clipboard.writeText(value);
      setCopiedField(field);
      window.setTimeout(
        () => setCopiedField((current) => (current === field ? null : current)),
        1600,
      );
    } catch {
      setCopyError("Could not copy to the clipboard.");
    }
  }

  async function saveWorkspaceName() {
    if (!settings) return;

    setError(null);
    setNotice(null);
    setSavingWorkspace(true);
    try {
      const organization = await api.organizations.update(
        settings.organization.id,
        workspaceName,
      );
      setSettings((current) =>
        current
          ? {
              ...current,
              organization: {
                ...current.organization,
                name: organization.name,
              },
            }
          : current,
      );
      setWorkspaceName(organization.name);
      await auth.refresh();
      setNotice("Workspace name updated.");
    } catch (err: unknown) {
      setError(
        err instanceof Error ? err.message : "Could not update workspace.",
      );
    } finally {
      setSavingWorkspace(false);
    }
  }

  if (loading && !settings) {
    return (
      <StateMessage state="loading" variant="page" message="Loading settings" />
    );
  }

  if (!settings) {
    return (
      <StateMessage
        state="error"
        variant="panel"
        message={error ?? "Could not load settings."}
      />
    );
  }

  const canManageWorkspace = ["owner", "admin"].includes(
    settings.organization.role,
  );

  return (
    <div className="max-w-4xl space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">Settings</h1>
      </div>

      {copyError && (
        <StateMessage
          state="error"
          variant="banner"
          message={copyError}
          onClose={() => setCopyError(null)}
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

      <SettingsSection
        title="Connect your AI assistant"
        description="Connect an MCP client, authorize with your Settra account, and choose the workspace it may access."
      >
        {settings.deployment_mode === "self_hosted" && (
          <>
            <ReadOnlyField
              id="product-name"
              label="Connection name"
              value={settings.product_name}
              copied={copiedField === "product-name"}
              onCopy={() =>
                void copyValue("product-name", settings.product_name)
              }
            />
            <ReadOnlyField
              id="ai-client-description"
              label="Connection description"
              value={settings.ai_client_description}
              multiline
              rows={4}
              copied={copiedField === "ai-client-description"}
              onCopy={() =>
                void copyValue(
                  "ai-client-description",
                  settings.ai_client_description,
                )
              }
            />
            <ReadOnlyField
              id="mcp-json"
              label="MCP configuration"
              value={mcpJson}
              multiline
              monospace
              copied={copiedField === "mcp-json"}
              onCopy={() => void copyValue("mcp-json", mcpJson)}
            />
          </>
        )}

        <ReadOnlyField
          id="mcp-url"
          label="MCP server URL"
          value={settings.mcp_url}
          copied={copiedField === "mcp-url"}
          onCopy={() => void copyValue("mcp-url", settings.mcp_url)}
        />

        <div className="grid gap-3 sm:grid-cols-3">
          <ConnectionFact label="Transport" value="Streamable HTTP" />
          <ConnectionFact label="Authentication" value="OAuth" />
          <ConnectionFact
            label="Current workspace"
            value={settings.organization.name}
          />
        </div>

        {!settings.oauth.enabled && (
          <StateMessage
            state="warning"
            variant="banner"
            message="MCP OAuth is disabled in this deployment. Clients cannot connect until an administrator enables it."
          />
        )}

        <div className="space-y-3 pt-1">
          <h3 className="text-sm font-medium">Setup guides</h3>

          <ProviderGuide
            title="Codex"
            description="Codex CLI, desktop app, or IDE extension"
            icon={<Terminal />}
            defaultOpen
          >
            <ol className="list-decimal space-y-3 pl-5 text-sm text-muted-foreground marker:text-foreground">
              <li className="pl-1">
                Add the remote MCP server from a terminal.
                <CopyableCode
                  label="Codex add command"
                  value={codexAddCommand}
                  copied={copiedField === "codex-add-command"}
                  onCopy={() =>
                    void copyValue("codex-add-command", codexAddCommand)
                  }
                />
              </li>
              <li className="pl-1">
                Start a read-only OAuth login.
                <CopyableCode
                  label="Codex login command"
                  value={codexLoginCommand}
                  copied={copiedField === "codex-login-command"}
                  onCopy={() =>
                    void copyValue("codex-login-command", codexLoginCommand)
                  }
                />
              </li>
              <li className="pl-1">
                Finish the browser sign-in and select the Settra workspace to
                grant. Restart Codex if the new server is not visible, then use
                <span className="mx-1 rounded border bg-muted px-1 py-0.5 font-mono text-xs text-foreground">
                  /mcp
                </span>
                to confirm it is connected.
              </li>
            </ol>
            <p className="mt-3 text-xs text-muted-foreground">
              Owners and admins can request
              <span className="mx-1 font-mono text-foreground">
                settra:read,settra:write
              </span>
              when they need semantic overlay tools. Members and viewers remain
              read-only.
            </p>
            <DocumentationLink href="https://developers.openai.com/codex/mcp">
              Codex MCP documentation
            </DocumentationLink>
          </ProviderGuide>

          <ProviderGuide
            title="ChatGPT"
            description="Custom MCP app in a supported ChatGPT workspace"
            icon={<MessageSquareText />}
          >
            <ol className="list-decimal space-y-2 pl-5 text-sm text-muted-foreground marker:text-foreground">
              <li className="pl-1">
                Enable developer mode for your ChatGPT workspace or account.
              </li>
              <li className="pl-1">
                Open <span className="text-foreground">Settings → Apps</span>,
                create a custom app, and enter the MCP server URL above.
              </li>
              <li className="pl-1">
                Choose OAuth authentication and scan the server tools.
              </li>
              <li className="pl-1">
                Complete the Settra sign-in, choose the workspace to grant, and
                finish creating the app.
              </li>
            </ol>
            <DocumentationLink href="https://help.openai.com/en/articles/12584461-developer-mode-and-full-mcp-connectors-in-chatgpt">
              ChatGPT custom MCP app documentation
            </DocumentationLink>
          </ProviderGuide>

          <ProviderGuide
            title="Other MCP clients"
            description="Clients that support remote Streamable HTTP servers"
            icon={<PlugZap />}
          >
            <ol className="list-decimal space-y-2 pl-5 text-sm text-muted-foreground marker:text-foreground">
              <li className="pl-1">Add a remote or custom MCP server.</li>
              <li className="pl-1">
                Select <span className="text-foreground">Streamable HTTP</span>
                and paste the MCP server URL above.
              </li>
              <li className="pl-1">
                Select OAuth. If prompted for client registration, choose
                dynamic client registration (DCR).
              </li>
              <li className="pl-1">
                Sign in to Settra and select the workspace this client may
                access. You do not need to create or paste an API token.
              </li>
            </ol>
          </ProviderGuide>
        </div>

        <div className="rounded-xl border bg-muted/25 p-4">
          <h3 className="text-sm font-medium">Verify the connection</h3>
          <p className="mt-1 text-sm text-muted-foreground">
            Start a new client conversation and try these in order:
          </p>
          <ol className="mt-3 list-decimal space-y-2 pl-5 text-sm marker:text-muted-foreground">
            <li className="pl-1">
              “List the collections available in Settra.”
            </li>
            <li className="pl-1">
              “Open the first collection and summarize its cubes.”
            </li>
            <li className="pl-1">“Query one cube for five rows.”</li>
          </ol>
          <p className="mt-3 text-xs text-muted-foreground">
            Successful calls appear on the Requests page. Start with the global
            URL above; collection-specific URLs are optional and use
            <span className="ml-1 font-mono text-foreground">
              /mcp/collections/&lt;collection-slug&gt;
            </span>
            .
          </p>
        </div>
      </SettingsSection>

      <SettingsSection
        title="Workspace"
        description="Your current data boundary."
      >
        {settings.deployment_mode === "self_hosted" && (
          <ReadOnlyField
            id="public-url"
            label="Application URL"
            value={settings.public_url}
            copied={copiedField === "public-url"}
            onCopy={() => void copyValue("public-url", settings.public_url)}
          />
        )}
        <div className="space-y-1.5">
          <div className="flex items-center gap-2">
            <Label htmlFor="organization-name">Workspace name</Label>
            <Badge variant="secondary">{settings.organization.role}</Badge>
          </div>
          <div className="flex gap-2">
            <Input
              id="organization-name"
              value={workspaceName}
              readOnly={!canManageWorkspace}
              onChange={(event) => setWorkspaceName(event.target.value)}
            />
            {canManageWorkspace && (
              <Button
                type="button"
                variant="outline"
                disabled={
                  savingWorkspace ||
                  !workspaceName.trim() ||
                  workspaceName.trim() === settings.organization.name
                }
                onClick={() => void saveWorkspaceName()}
              >
                {savingWorkspace ? "Saving…" : "Save"}
              </Button>
            )}
          </div>
        </div>
      </SettingsSection>

      <SettingsSection
        title="MCP authorization"
        description={
          settings.deployment_mode === "managed"
            ? "AI clients authorize through your Settra account. Each grant is bound to the workspace you choose during OAuth."
            : "AI clients use your account login to authorize access to this workspace. Your password is never exposed here."
        }
        badge={
          <Badge variant={settings.oauth.enabled ? "success" : "secondary"}>
            {settings.oauth.enabled ? "Enabled" : "Disabled"}
          </Badge>
        }
      >
        <ReadOnlyField
          id="oauth-identity"
          label="Signed-in Settra account"
          value={settings.oauth.authorization_identity}
          copied={copiedField === "oauth-identity"}
          onCopy={() =>
            void copyValue(
              "oauth-identity",
              settings.oauth.authorization_identity,
            )
          }
        />
      </SettingsSection>
    </div>
  );
}

function SettingsSection({
  title,
  description,
  badge,
  children,
}: {
  title: string;
  description: string;
  badge?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="space-y-4 border-t pt-6 first:border-t-0 first:pt-0">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-base font-semibold">{title}</h2>
        {badge}
      </div>
      <p className="-mt-2 text-sm text-muted-foreground">{description}</p>
      <div className="space-y-4">{children}</div>
    </section>
  );
}

function ConnectionFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border bg-muted/20 px-3 py-2.5">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-0.5 truncate text-sm font-medium" title={value}>
        {value}
      </p>
    </div>
  );
}

function ProviderGuide({
  title,
  description,
  icon,
  defaultOpen = false,
  children,
}: {
  title: string;
  description: string;
  icon: ReactNode;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  return (
    <details
      open={defaultOpen}
      className="group overflow-hidden rounded-xl border bg-card"
    >
      <summary className="flex cursor-pointer list-none items-center gap-3 px-4 py-3 outline-none select-none hover:bg-muted/40 focus-visible:ring-3 focus-visible:ring-inset focus-visible:ring-ring/50 [&::-webkit-details-marker]:hidden">
        <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-muted text-muted-foreground [&_svg]:size-4">
          {icon}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-medium">{title}</span>
          <span className="block truncate text-xs text-muted-foreground">
            {description}
          </span>
        </span>
        <ChevronDown className="size-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180" />
      </summary>
      <div className="border-t px-4 py-4">{children}</div>
    </details>
  );
}

function CopyableCode({
  label,
  value,
  copied,
  onCopy,
}: {
  label: string;
  value: string;
  copied: boolean;
  onCopy: () => void;
}) {
  return (
    <div className="relative mt-2 rounded-lg border bg-muted/50">
      <pre className="overflow-x-auto px-3 py-2.5 pr-11 font-mono text-xs leading-5 text-foreground">
        <code>{value}</code>
      </pre>
      <CopyButton
        label={label}
        copied={copied}
        disabled={!value}
        className="absolute right-1.5 top-1.5"
        onClick={onCopy}
      />
    </div>
  );
}

function DocumentationLink({
  href,
  children,
}: {
  href: string;
  children: ReactNode;
}) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-primary hover:text-primary/80"
    >
      {children}
      <ExternalLink className="size-3" />
    </a>
  );
}

function ReadOnlyField({
  id,
  label,
  value,
  secret = false,
  multiline = false,
  monospace = false,
  rows = 9,
  copied,
  onCopy,
}: {
  id: string;
  label: string;
  value: string;
  secret?: boolean;
  multiline?: boolean;
  monospace?: boolean;
  rows?: number;
  copied: boolean;
  onCopy: () => void;
}) {
  const empty = value.length === 0;

  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <div className="relative">
        {multiline ? (
          <>
            <textarea
              id={id}
              value={value}
              readOnly
              rows={rows}
              spellCheck={false}
              className={cn(
                "w-full min-w-0 resize-none rounded-lg border border-input bg-muted/30 px-3 py-2 pr-10 text-sm leading-5 outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/20",
                monospace && "min-h-48 font-mono text-xs",
              )}
            />
            <CopyButton
              label={label}
              copied={copied}
              disabled={empty}
              className="absolute right-1 top-1"
              onClick={onCopy}
            />
          </>
        ) : secret ? (
          <>
            <SecretInput
              id={id}
              value={value}
              readOnly
              autoComplete="off"
              placeholder="Not configured"
              className="pr-16 font-mono"
            />
            <CopyButton
              label={label}
              copied={copied}
              disabled={empty}
              className="absolute right-8 top-1/2 -translate-y-1/2"
              onClick={onCopy}
            />
          </>
        ) : (
          <>
            <Input
              id={id}
              value={value}
              readOnly
              spellCheck={false}
              placeholder="Not configured"
              className="pr-10 font-mono"
            />
            <CopyButton
              label={label}
              copied={copied}
              disabled={empty}
              className="absolute right-0.5 top-1/2 -translate-y-1/2"
              onClick={onCopy}
            />
          </>
        )}
      </div>
      {empty && (
        <p className="text-xs text-muted-foreground">
          Not configured in this environment.
        </p>
      )}
    </div>
  );
}

function CopyButton({
  label,
  copied,
  disabled,
  className,
  onClick,
}: {
  label: string;
  copied: boolean;
  disabled: boolean;
  className?: string;
  onClick: () => void;
}) {
  return (
    <Tooltip
      content={copied ? "Copied" : `Copy ${label}`}
      className={className}
    >
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        disabled={disabled}
        aria-label={copied ? `${label} copied` : `Copy ${label}`}
        className={cn(
          "text-muted-foreground hover:text-foreground",
          copied && "text-primary dark:text-primary",
        )}
        onClick={onClick}
      >
        {copied ? <Check className="size-4" /> : <Copy className="size-4" />}
      </Button>
    </Tooltip>
  );
}
