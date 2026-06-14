import httpx

from typing import Any

from app.messaging.base import (
    IncomingMessage,
    MessagingProvider,
    MessagingProviderError,
)


class TelegramProvider(MessagingProvider):
    key = "telegram"
    supports_status_updates = True

    async def validate_config(
        self,
        config: dict[str, Any],
        secrets: dict[str, Any],
    ) -> None:
        token = str(secrets.get("bot_token") or "").strip()

        if not token:
            raise MessagingProviderError("Telegram bot token is required")

    async def parse_webhook(
        self,
        request: Any,
        config: dict[str, Any],
        secrets: dict[str, Any],
    ) -> list[IncomingMessage]:
        expected_secret = str(secrets.get("webhook_secret_token") or "").strip()

        if expected_secret:
            provided_secret = request.headers.get(
                "X-Telegram-Bot-Api-Secret-Token",
                "",
            )

            if provided_secret != expected_secret:
                raise MessagingProviderError("Invalid Telegram webhook secret")

        payload = await request.json()
        message = payload.get("message") or payload.get("edited_message") or {}
        text = message.get("text") or ""

        if not text.strip():
            return []

        chat = message.get("chat") or {}
        sender = message.get("from") or {}
        chat_id = str(chat.get("id") or "").strip()

        if not chat_id:
            return []

        allowed_chat_ids = _split_csv(config.get("allowed_chat_ids"))

        if allowed_chat_ids and chat_id not in allowed_chat_ids:
            return []

        update_id = payload.get("update_id")
        message_id = message.get("message_id")
        external_message_id = (
            f"{update_id}:{message_id}" if update_id is not None else str(message_id)
        )

        return [
            IncomingMessage(
                provider=self.key,
                external_message_id=external_message_id,
                conversation_id=chat_id,
                sender_id=str(sender.get("id") or chat_id),
                text=text.strip(),
                raw=payload,
            )
        ]

    async def send(
        self,
        to: str,
        text: str,
        config: dict[str, Any],
        secrets: dict[str, Any],
    ) -> dict[str, Any]:
        token = str(secrets.get("bot_token") or "").strip()

        if not token:
            raise MessagingProviderError("Telegram bot token is required")

        responses = []

        async with httpx.AsyncClient(timeout=30) as client:
            for chunk in _telegram_chunks(text):
                responses.append(await _send_message(client, token, to, chunk))

        return {"messages": responses}

    async def send_status(
        self,
        to: str,
        text: str,
        config: dict[str, Any],
        secrets: dict[str, Any],
    ) -> dict[str, Any]:
        token = str(secrets.get("bot_token") or "").strip()

        if not token:
            raise MessagingProviderError("Telegram bot token is required")

        async with httpx.AsyncClient(timeout=30) as client:
            payload = await _send_message(client, token, to, text)

        return {
            "chat_id": to,
            "message_id": (payload.get("result") or {}).get("message_id"),
            "payload": payload,
        }

    async def update_status(
        self,
        status_ref: dict[str, Any],
        text: str,
        config: dict[str, Any],
        secrets: dict[str, Any],
    ) -> dict[str, Any] | None:
        token = str(secrets.get("bot_token") or "").strip()
        chat_id = status_ref.get("chat_id")
        message_id = status_ref.get("message_id")

        if not token or not chat_id or not message_id:
            return None

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"https://api.telegram.org/bot{token}/editMessageText",
                json={"chat_id": chat_id, "message_id": message_id, "text": text},
            )

            if (
                response.status_code == 400
                and "message is not modified" in response.text
            ):
                return None

            response.raise_for_status()
            return response.json()


def _split_csv(value: Any) -> set[str]:
    return {
        item.strip() for item in str(value or "").split(",") if item and item.strip()
    }


def _telegram_chunks(text: str) -> list[str]:
    limit = 3900
    clean = text.strip() or "I could not produce a response."

    return [clean[index : index + limit] for index in range(0, len(clean), limit)]


async def _send_message(
    client: httpx.AsyncClient,
    token: str,
    chat_id: str,
    text: str,
) -> dict[str, Any]:
    response = await client.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text},
    )

    response.raise_for_status()
    return response.json()
