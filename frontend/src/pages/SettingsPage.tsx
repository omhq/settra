import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Check, Copy } from "lucide-react";

import { api, type DeploymentSettings } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SecretInput } from "@/components/ui/secret-input";
import { StateMessage } from "@/components/ui/state-message";
import { Tooltip } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

export default function SettingsPage() {
  const [settings, setSettings] = useState<DeploymentSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copyError, setCopyError] = useState<string | null>(null);
  const [copiedField, setCopiedField] = useState<string | null>(null);

  useEffect(() => {
    api.settings
      .get()
      .then(setSettings)
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
                settra: {
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

  if (loading && !settings) {
    return (
      <StateMessage state="loading" variant="page" message="Loading settings" />
    );
  }

  if (error || !settings) {
    return (
      <StateMessage
        state="error"
        variant="panel"
        message={error ?? "Could not load settings."}
      />
    );
  }

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

      <SettingsSection
        title="MCP connection"
        description="Use these details to connect an MCP-compatible AI client to Settra."
      >
        <ReadOnlyField
          id="mcp-url"
          label="MCP URL"
          value={settings.mcp_url}
          copied={copiedField === "mcp-url"}
          onCopy={() => void copyValue("mcp-url", settings.mcp_url)}
        />
        <ReadOnlyField
          id="mcp-json"
          label="MCP JSON"
          value={mcpJson}
          multiline
          copied={copiedField === "mcp-json"}
          onCopy={() => void copyValue("mcp-json", mcpJson)}
        />
      </SettingsSection>

      <SettingsSection
        title="Admin access"
        description="Admin UI and API credentials."
      >
        <ReadOnlyField
          id="settra-url"
          label="Settra URL"
          value={settings.settra_url}
          copied={copiedField === "settra-url"}
          onCopy={() => void copyValue("settra-url", settings.settra_url)}
        />
        <div className="grid gap-4 sm:grid-cols-2">
          <ReadOnlyField
            id="basic-auth-username"
            label="Basic Auth username"
            value={settings.basic_auth.username}
            copied={copiedField === "basic-auth-username"}
            onCopy={() =>
              void copyValue(
                "basic-auth-username",
                settings.basic_auth.username,
              )
            }
          />
          <ReadOnlyField
            id="basic-auth-password"
            label="Basic Auth password"
            value={settings.basic_auth.password}
            secret
            copied={copiedField === "basic-auth-password"}
            onCopy={() =>
              void copyValue(
                "basic-auth-password",
                settings.basic_auth.password,
              )
            }
          />
        </div>
      </SettingsSection>

      <SettingsSection
        title="OAuth login"
        description="MCP client credentials."
        badge={
          <Badge variant={settings.oauth.enabled ? "success" : "secondary"}>
            {settings.oauth.enabled ? "Enabled" : "Disabled"}
          </Badge>
        }
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <ReadOnlyField
            id="oauth-username"
            label="OAuth login username"
            value={settings.oauth.username}
            copied={copiedField === "oauth-username"}
            onCopy={() =>
              void copyValue("oauth-username", settings.oauth.username)
            }
          />
          <ReadOnlyField
            id="oauth-password"
            label="OAuth login password"
            value={settings.oauth.password}
            secret
            copied={copiedField === "oauth-password"}
            onCopy={() =>
              void copyValue("oauth-password", settings.oauth.password)
            }
          />
        </div>
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

function ReadOnlyField({
  id,
  label,
  value,
  secret = false,
  multiline = false,
  copied,
  onCopy,
}: {
  id: string;
  label: string;
  value: string;
  secret?: boolean;
  multiline?: boolean;
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
              rows={9}
              spellCheck={false}
              className="min-h-48 w-full min-w-0 resize-none rounded-lg border border-input bg-muted/30 px-3 py-2 pr-10 font-mono text-xs leading-5 outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/20"
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
