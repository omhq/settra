# Telegram Channel

This channel lets a Telegram bot send messages into Settra chat and receive
progress updates plus final answers.

## Webhook setup

Assumptions:

- The API is reachable from the internet at `https://<your-host>`.
- `<your-host>` is a secure, fully qualified HTTPS host for wherever your deployment lives.
- For local testing, an HTTPS tunnel such as ngrok can forward to the API port.
- The frontend is available from your deployment, or at `http://localhost:5173` during local development.

### 1. Create a Telegram bot

1. Open Telegram and message `@BotFather`.
2. Run `/newbot`.
3. Copy the bot token. It looks like `123456:ABC...`.

### 2. Create the Settra channel

1. Open `/channels/new` in the frontend.
2. Select `Telegram`.
3. Fill in:
   - `Channel name`: any label, for example `Telegram test`.
   - `Default model`: the model the agent should use for mobile chat.
   - `Default connections`: the data connections this bot can query.
   - `Bot Token`: the token from BotFather.
   - `Webhook Secret Token`: optional but recommended; any random string.
   - `Allowed Chat IDs`: leave blank for the first test.
   - `Progress Mode`: `compact`.
4. Save the channel.

After saving, the edit page shows a webhook path like:

```text
/api/messaging/webhooks/telegram/<config_id>
```

Combine your public HTTPS host with that path:

```text
https://<your-host>/api/messaging/webhooks/telegram/<config_id>
```

The edit page also generates copyable `setWebhook` commands. Set `Public API
URL` to `https://<your-host>` first.

You can make that field default to your public API URL by starting the app
container with:

```bash
PUBLIC_API_URL=https://<your-host> docker compose up app
```

For deployed installs, set `PUBLIC_API_URL` on the app container. If the
frontend and API are served from the same public origin, the browser origin
fallback is usually enough.

### 3. Register the Telegram webhook

Without a webhook secret:

```bash
curl -X POST "https://api.telegram.org/bot<bot_token>/setWebhook" \
  --data-urlencode "url=https://<your-host>/api/messaging/webhooks/telegram/<config_id>"
```

With a webhook secret:

```bash
curl -X POST "https://api.telegram.org/bot<bot_token>/setWebhook" \
  --data-urlencode "url=https://<your-host>/api/messaging/webhooks/telegram/<config_id>" \
  --data-urlencode "secret_token=<same_webhook_secret_token>"
```

Check Telegram's webhook status:

```bash
curl "https://api.telegram.org/bot<bot_token>/getWebhookInfo"
```

### 4. Send a test message

Open your bot in Telegram and send:

```text
/start
```

Then send a normal analytics question. The agent should reply with progress and a
final answer.

### 5. Lock down Allowed Chat IDs

For the first test, `Allowed Chat IDs` can stay blank. After a Telegram message
arrives, the Telegram chat ID is stored as `external_conversation_id` in
`messaging_events`.

Put the ID into `Allowed Chat IDs` and save the channel. Multiple IDs can be
comma-separated. Telegram group and supergroup IDs are often negative.

## Supported commands

- `/start` or `/help` shows commands.
- `/new` starts a fresh chat for this Telegram conversation.
- `/clear` clears the current chat.
- `/delete` deletes the current chat and removes the Telegram mapping.

## Troubleshooting

- Telegram must use a public HTTPS URL for the API, not `localhost` and not the Vite frontend URL.
- If `Webhook Secret Token` is set, `secret_token` must be passed to `setWebhook` with the same value.
- If `Allowed Chat IDs` is set incorrectly, messages from other Telegram chats will be ignored.
- Use `docker compose logs -f app` while testing to watch webhook requests and worker activity.
