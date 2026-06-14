import asyncio
import logging

from typing import Any

from fastapi import HTTPException

from app.messaging.command_handler import handle_command
from app.messaging.commands import parse_messaging_command
from app.messaging.configs import get_messaging_config
from app.messaging.discovery import load_provider
from app.messaging.ids import job_chat_request_id
from app.messaging.jobs import (
    attach_job_conversation,
    claim_next_job,
    complete_job,
    fail_job,
    recover_running_jobs,
)
from app.messaging.progress import (
    ProgressState,
    send_outbound_message,
    send_progress,
)
from app.messaging.store import (
    attach_event_conversation,
    create_conversation,
    get_conversation,
    mark_event_failed,
)
from app.schemas import ChatRequest

logger = logging.getLogger(__name__)

__all__ = [
    "run_messaging_worker",
]


async def run_messaging_worker(poll_interval: float = 1.0) -> None:
    recovered = await recover_running_jobs()
    if recovered:
        logger.info("Recovered %s running messaging jobs", recovered)

    logger.info("Messaging worker started")

    while True:
        job = await claim_next_job()

        if not job:
            await asyncio.sleep(poll_interval)
            continue

        try:
            await _process_job(job)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(
                "Messaging job failed job_id=%s error=%s",
                job.get("id"),
                exc,
            )
            await fail_job(int(job["id"]), str(exc))
            await mark_event_failed(int(job["inbound_event_id"]), str(exc))


async def _process_job(job: dict[str, Any]) -> None:
    config = await get_messaging_config(
        int(job["config_id"]),
        include_secrets=True,
        allow_inactive=False,
    )

    if not config:
        raise RuntimeError("Messaging config not found")

    provider = load_provider(config["provider"])
    external_conversation_id = str(job["external_conversation_id"])
    conversation = await get_conversation(config["id"], external_conversation_id)
    thread_id = conversation["chat_thread_id"] if conversation else None
    command = parse_messaging_command(str(job["message_text"] or ""))

    if command:
        conversation_id = await handle_command(
            command=command,
            provider=provider,
            config=config,
            job=job,
            conversation=conversation,
        )

        await complete_job(int(job["id"]), conversation_id)
        return

    status_state = ProgressState()
    final_event = await _run_chat_for_job(
        config=config,
        provider=provider,
        job=job,
        conversation=conversation,
        thread_id=thread_id,
        external_conversation_id=external_conversation_id,
        status_state=status_state,
    )
    conversation = await get_conversation(config["id"], external_conversation_id)

    await _finish_job(
        config=config,
        provider=provider,
        job=job,
        conversation=conversation,
        external_conversation_id=external_conversation_id,
        final_event=final_event,
    )


async def _run_chat_for_job(
    *,
    config: dict[str, Any],
    provider: Any,
    job: dict[str, Any],
    conversation: dict[str, Any] | None,
    thread_id: int | None,
    external_conversation_id: str,
    status_state: ProgressState,
) -> dict[str, Any]:
    request_id = job_chat_request_id(config["id"], job)
    final_event: dict[str, Any] | None = None

    try:
        # TODO: move to a more core module to avoid circular imports
        from app.routers.chat_runner import chat_events

        async for event in chat_events(
            ChatRequest(
                connection_ids=config["connection_ids"],
                model_config_id=config["model_config_id"],
                message=str(job["message_text"] or ""),
                thread_id=thread_id,
                request_id=request_id,
            )
        ):
            event_type = event.get("type")

            if event_type == "thread":
                conversation = await _ensure_job_conversation(
                    config=config,
                    job=job,
                    conversation=conversation,
                    external_conversation_id=external_conversation_id,
                    thread_id=int(event["thread_id"]),
                )
                await send_progress(
                    provider=provider,
                    config=config,
                    to=external_conversation_id,
                    conversation_id=conversation["id"],
                    text="Thinking...",
                    status_state=status_state,
                    force_send=True,
                )
            elif event_type == "step":
                await send_progress(
                    provider=provider,
                    config=config,
                    to=external_conversation_id,
                    conversation_id=conversation["id"] if conversation else None,
                    text=str(event.get("label") or "Working..."),
                    status_state=status_state,
                )
            elif event_type in {"result", "error"}:
                final_event = event
    except HTTPException as exc:
        final_event = {
            "type": "error",
            "message": str(exc.detail),
            "thread_id": thread_id,
        }
    except Exception as exc:
        final_event = {
            "type": "error",
            "message": f"Chat failed: {exc}",
            "thread_id": thread_id,
        }
        logger.exception("Messaging chat execution failed job_id=%s", job["id"])

    if final_event is None:
        return {
            "type": "error",
            "message": "Chat completed without a result",
            "thread_id": thread_id,
        }

    return final_event


async def _ensure_job_conversation(
    *,
    config: dict[str, Any],
    job: dict[str, Any],
    conversation: dict[str, Any] | None,
    external_conversation_id: str,
    thread_id: int,
) -> dict[str, Any]:
    if not conversation:
        conversation = await create_conversation(
            config_id=config["id"],
            external_conversation_id=external_conversation_id,
            external_user_id=job.get("external_user_id"),
            chat_thread_id=thread_id,
        )
        await attach_event_conversation(
            int(job["inbound_event_id"]),
            conversation["id"],
        )

    await attach_job_conversation(int(job["id"]), conversation["id"])

    return conversation


async def _finish_job(
    *,
    config: dict[str, Any],
    provider: Any,
    job: dict[str, Any],
    conversation: dict[str, Any] | None,
    external_conversation_id: str,
    final_event: dict[str, Any],
) -> None:
    answer = (
        final_event.get("answer")
        or final_event.get("message")
        or "I could not produce a response."
    )

    await send_outbound_message(
        provider=provider,
        config=config,
        to=external_conversation_id,
        conversation_id=conversation["id"] if conversation else None,
        text=str(answer),
    )

    if final_event.get("type") == "error":
        await fail_job(int(job["id"]), str(answer))
        await mark_event_failed(int(job["inbound_event_id"]), str(answer))
        return

    await complete_job(
        int(job["id"]),
        conversation["id"] if conversation else None,
    )
