import logging

from typing import Any

from fastapi import HTTPException, Request

from app.messaging.base import IncomingMessage, MessagingProviderError
from app.messaging.configs import get_messaging_config
from app.messaging.discovery import load_provider
from app.messaging.jobs import enqueue_messaging_job
from app.messaging.store import get_conversation, record_inbound_event

logger = logging.getLogger(__name__)

__all__ = [
    "process_webhook",
    "verify_webhook",
]


async def process_webhook(
    provider_key: str,
    config_id: int,
    request: Request,
) -> dict[str, Any]:
    config = await get_messaging_config(
        config_id,
        include_secrets=True,
        allow_inactive=False,
    )

    if not config:
        raise HTTPException(404, "Messaging config not found")

    if config["provider"] != provider_key:
        raise HTTPException(404, "Messaging config does not match provider")

    provider = load_provider(provider_key)

    try:
        messages = await provider.parse_webhook(
            request,
            config["config"],
            config.get("secrets", {}),
        )
    except MessagingProviderError as exc:
        raise HTTPException(401, str(exc))

    handled: list[dict[str, Any]] = []

    for message in messages:
        handled.append(await _process_message(config, message))

    return {"ok": True, "received": len(messages), "handled": handled}


async def verify_webhook(
    provider_key: str,
    config_id: int,
    request: Request,
):
    config = await get_messaging_config(
        config_id,
        include_secrets=True,
        allow_inactive=False,
    )

    if not config:
        raise HTTPException(404, "Messaging config not found")

    if config["provider"] != provider_key:
        raise HTTPException(404, "Messaging config does not match provider")

    provider = load_provider(provider_key)

    try:
        return await provider.verify_webhook(
            request,
            config["config"],
            config.get("secrets", {}),
        )
    except MessagingProviderError as exc:
        raise HTTPException(401, str(exc))


async def _process_message(
    config: dict[str, Any],
    message: IncomingMessage,
) -> dict[str, Any]:
    if not message.text.strip():
        return {"status": "ignored", "reason": "empty_message"}

    conversation = await get_conversation(config["id"], message.conversation_id)
    inbound_event_id = await record_inbound_event(
        config_id=config["id"],
        conversation_id=conversation["id"] if conversation else None,
        message=message,
    )

    if inbound_event_id is None:
        return {
            "status": "duplicate",
            "external_message_id": message.external_message_id,
        }

    job = await enqueue_messaging_job(
        config_id=config["id"],
        inbound_event_id=inbound_event_id,
        conversation_id=conversation["id"] if conversation else None,
    )

    return {
        "status": job["status"],
        "job_id": job["id"],
        "conversation_id": conversation["id"] if conversation else None,
        "external_message_id": message.external_message_id,
    }
