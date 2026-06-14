import logging

from typing import Any

from pydantic import BaseModel, ConfigDict

from app.messaging.store import record_outbound_event

logger = logging.getLogger(__name__)


class ProgressState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sent_count: int = 0
    last_text: str = ""
    ref: dict[str, Any] | None = None


async def send_outbound_message(
    *,
    provider: Any,
    config: dict[str, Any],
    to: str,
    conversation_id: int | None,
    text: str,
) -> dict[str, Any]:
    payload = await provider.send(
        to,
        text,
        config["config"],
        config.get("secrets", {}),
    )
    await record_outbound_event(
        config_id=config["id"],
        conversation_id=conversation_id,
        to=to,
        text=text,
        payload=payload or {},
    )

    return payload or {}


async def send_progress(
    *,
    provider: Any,
    config: dict[str, Any],
    to: str,
    conversation_id: int | None,
    text: str,
    status_state: ProgressState,
    force_send: bool = False,
) -> None:
    mode = str((config.get("config") or {}).get("progress_mode") or "compact").lower()

    if mode == "silent":
        return

    if text == status_state.last_text:
        return

    status_state.last_text = text

    if provider.supports_status_updates and status_state.ref:
        try:
            await provider.update_status(
                status_state.ref,
                text,
                config["config"],
                config.get("secrets", {}),
            )
        except Exception as exc:
            logger.warning("Could not update messaging status: %s", exc)
        return

    max_messages = 4 if mode == "verbose" else 1

    if not force_send and status_state.sent_count >= max_messages:
        return

    try:
        status_ref = await provider.send_status(
            to,
            text,
            config["config"],
            config.get("secrets", {}),
        )
        status_state.sent_count += 1
        if provider.supports_status_updates and status_ref:
            status_state.ref = status_ref
        await record_outbound_event(
            config_id=config["id"],
            conversation_id=conversation_id,
            to=to,
            text=text,
            payload=status_ref or {},
        )
    except Exception as exc:
        logger.warning("Could not send messaging status: %s", exc)
