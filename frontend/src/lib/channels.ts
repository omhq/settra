export const PUBLIC_API_URL_STORAGE_KEY = "settra:public-api-url";

export function channelWebhookPath(provider: string, configId: number) {
  return `/api/messaging/webhooks/${encodeURIComponent(provider)}/${configId}`;
}

export function channelWebhookUrl(
  provider: string,
  configId: number,
  publicApiUrl?: string,
) {
  const path = channelWebhookPath(provider, configId);
  const baseUrl = normalizePublicApiUrl(publicApiUrl);

  if (baseUrl) return `${baseUrl}${path}`;
  if (typeof window === "undefined") return path;

  return `${window.location.origin}${path}`;
}

export function defaultPublicApiUrl() {
  const stored = readStoredPublicApiUrl();

  if (stored) return stored;
  if (typeof window === "undefined") return "";

  return window.location.origin;
}

export function readStoredPublicApiUrl() {
  if (typeof window === "undefined") return "";

  return normalizePublicApiUrl(
    window.localStorage.getItem(PUBLIC_API_URL_STORAGE_KEY),
  );
}

export function storePublicApiUrl(value: string) {
  if (typeof window === "undefined") return;

  const normalized = normalizePublicApiUrl(value);

  if (normalized) {
    window.localStorage.setItem(PUBLIC_API_URL_STORAGE_KEY, normalized);
    return;
  }

  window.localStorage.removeItem(PUBLIC_API_URL_STORAGE_KEY);
}

export function normalizePublicApiUrl(value: unknown) {
  const text = String(value ?? "").trim();

  if (!text) return "";

  return text.replace(/\/+$/, "");
}

export function telegramSetWebhookCurl({
  botToken = "<bot_token>",
  webhookUrl,
  includeSecret = false,
}: {
  botToken?: string;
  webhookUrl: string;
  includeSecret?: boolean;
}) {
  const lines = [
    `curl -X POST "https://api.telegram.org/bot${botToken}/setWebhook" \\`,
    `  --data-urlencode "url=${webhookUrl}"`,
  ];

  if (includeSecret) {
    lines[lines.length - 1] += " \\";
    lines.push(`  --data-urlencode "secret_token=<webhook_secret_token>"`);
  }

  return lines.join("\n");
}
