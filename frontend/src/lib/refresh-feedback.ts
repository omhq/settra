const MINIMUM_REFRESH_FEEDBACK_MS = 300;

export async function waitForRefreshFeedback(startedAt: number) {
  const remaining = MINIMUM_REFRESH_FEEDBACK_MS - (Date.now() - startedAt);
  if (remaining <= 0) return;

  await new Promise<void>((resolve) => window.setTimeout(resolve, remaining));
}
