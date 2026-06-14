from typing import Any
from dataclasses import dataclass, field


class MessagingProviderError(ValueError):
    pass


@dataclass(frozen=True)
class IncomingMessage:
    provider: str
    external_message_id: str | None
    conversation_id: str
    sender_id: str | None
    text: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WebhookResponse:
    content: str
    status_code: int = 200
    media_type: str = "text/plain"
    headers: dict[str, str] = field(default_factory=dict)


class MessagingProvider:
    key = ""
    supports_status_updates = False

    async def validate_config(
        self,
        config: dict[str, Any],
        secrets: dict[str, Any],
    ) -> None:
        raise NotImplementedError

    async def verify_webhook(
        self,
        request: Any,
        config: dict[str, Any],
        secrets: dict[str, Any],
    ) -> WebhookResponse | None:
        return None

    async def parse_webhook(
        self,
        request: Any,
        config: dict[str, Any],
        secrets: dict[str, Any],
    ) -> list[IncomingMessage]:
        raise NotImplementedError

    async def send(
        self,
        to: str,
        text: str,
        config: dict[str, Any],
        secrets: dict[str, Any],
    ) -> dict[str, Any] | None:
        raise NotImplementedError

    async def send_status(
        self,
        to: str,
        text: str,
        config: dict[str, Any],
        secrets: dict[str, Any],
    ) -> dict[str, Any] | None:
        return await self.send(to, text, config, secrets)

    async def update_status(
        self,
        status_ref: dict[str, Any],
        text: str,
        config: dict[str, Any],
        secrets: dict[str, Any],
    ) -> dict[str, Any] | None:
        return None
