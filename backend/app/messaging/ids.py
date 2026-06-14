from typing import Any

from app.messaging.base import IncomingMessage


def job_chat_request_id(config_id: int, job: dict[str, Any]) -> str:
    provider_message_id = job.get("provider_message_id")
    suffix = provider_message_id or f"event:{job['inbound_event_id']}"

    return f"messaging:{config_id}:{suffix}"[:255]


def message_chat_request_id(
    config_id: int,
    message: IncomingMessage,
) -> str | None:
    if not message.external_message_id:
        return None

    return f"messaging:{config_id}:{message.external_message_id}"[:255]
