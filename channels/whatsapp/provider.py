import httpx

from typing import Any

from app.messaging.base import (
    IncomingMessage,
    MessagingProvider,
    MessagingProviderError,
    WebhookResponse,
)


class WhatsAppProvider(MessagingProvider):
    key = "whatsapp"

    async def validate_config(
        self,
        config: dict[str, Any],
        secrets: dict[str, Any],
    ) -> None:
        if not str(secrets.get("access_token") or "").strip():
            raise MessagingProviderError("WhatsApp access token is required")
        if not str(secrets.get("verify_token") or "").strip():
            raise MessagingProviderError("WhatsApp verify token is required")
        if not str(config.get("phone_number_id") or "").strip():
            raise MessagingProviderError("WhatsApp phone number ID is required")

    async def verify_webhook(
        self,
        request: Any,
        config: dict[str, Any],
        secrets: dict[str, Any],
    ) -> WebhookResponse | None:
        params = request.query_params
        mode = params.get("hub.mode")
        token = params.get("hub.verify_token")
        challenge = params.get("hub.challenge")
        expected = str(secrets.get("verify_token") or "").strip()

        if mode == "subscribe" and challenge and token == expected:
            return WebhookResponse(content=challenge, media_type="text/plain")

        raise MessagingProviderError("Invalid WhatsApp webhook verification")

    async def parse_webhook(
        self,
        request: Any,
        config: dict[str, Any],
        secrets: dict[str, Any],
    ) -> list[IncomingMessage]:
        payload = await request.json()
        messages: list[IncomingMessage] = []

        for entry in payload.get("entry", []) or []:
            for change in entry.get("changes", []) or []:
                value = change.get("value") or {}

                for message in value.get("messages", []) or []:
                    text = (message.get("text") or {}).get("body") or ""

                    if not text.strip():
                        continue

                    sender = str(message.get("from") or "").strip()
                    message_id = str(message.get("id") or "").strip()

                    if not sender:
                        continue

                    messages.append(
                        IncomingMessage(
                            provider=self.key,
                            external_message_id=message_id or None,
                            conversation_id=sender,
                            sender_id=sender,
                            text=text.strip(),
                            raw=message,
                        )
                    )

        return messages

    async def send(
        self,
        to: str,
        text: str,
        config: dict[str, Any],
        secrets: dict[str, Any],
    ) -> dict[str, Any]:
        access_token = str(secrets.get("access_token") or "").strip()
        phone_number_id = str(config.get("phone_number_id") or "").strip()

        if not access_token or not phone_number_id:
            raise MessagingProviderError("WhatsApp credentials are incomplete")

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"https://graph.facebook.com/v20.0/{phone_number_id}/messages",
                headers={"Authorization": f"Bearer {access_token}"},
                json={
                    "messaging_product": "whatsapp",
                    "to": to,
                    "type": "text",
                    "text": {"body": text.strip() or "I could not produce a response."},
                },
            )

            response.raise_for_status()
            return response.json()
