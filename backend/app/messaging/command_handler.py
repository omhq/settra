from typing import Any

from fastapi import HTTPException

from app.messaging.chat_threads import (
    clear_chat_thread,
    create_chat_thread,
    delete_chat_thread,
)
from app.messaging.commands import COMMAND_HELP, MessagingCommand
from app.messaging.progress import send_outbound_message
from app.messaging.store import (
    attach_event_conversation,
    create_conversation,
    delete_conversation,
    set_conversation_thread,
)


async def handle_command(
    *,
    command: MessagingCommand,
    provider: Any,
    config: dict[str, Any],
    job: dict[str, Any],
    conversation: dict[str, Any] | None,
) -> int | None:
    external_conversation_id = str(job["external_conversation_id"])
    conversation_id = int(conversation["id"]) if conversation else None

    if command.name == "help":
        await _send_command_reply(
            provider=provider,
            config=config,
            to=external_conversation_id,
            conversation_id=conversation_id,
            text=COMMAND_HELP,
        )
        return conversation_id

    if command.name == "unknown":
        await _send_command_reply(
            provider=provider,
            config=config,
            to=external_conversation_id,
            conversation_id=conversation_id,
            text=f"Unknown command: /{command.raw_name}\n\n{COMMAND_HELP}",
        )
        return conversation_id

    if command.name == "new":
        title = command.args or "New chat"

        try:
            thread_id = await create_chat_thread(config, title)
        except HTTPException as exc:
            await _send_command_reply(
                provider=provider,
                config=config,
                to=external_conversation_id,
                conversation_id=conversation_id,
                text=f"Could not start a new chat: {exc.detail}",
            )
            return conversation_id

        if conversation:
            conversation = await set_conversation_thread(
                conversation_id=int(conversation["id"]),
                external_user_id=job.get("external_user_id"),
                chat_thread_id=thread_id,
            )
        else:
            conversation = await create_conversation(
                config_id=config["id"],
                external_conversation_id=external_conversation_id,
                external_user_id=job.get("external_user_id"),
                chat_thread_id=thread_id,
            )

        conversation_id = int(conversation["id"])

        await attach_event_conversation(
            int(job["inbound_event_id"]),
            conversation_id,
        )
        await _send_command_reply(
            provider=provider,
            config=config,
            to=external_conversation_id,
            conversation_id=conversation_id,
            text=f"Started chat #{thread_id}. Send a message when you're ready.",
        )
        return conversation_id

    if command.name == "clear":
        if not conversation:
            await _send_command_reply(
                provider=provider,
                config=config,
                to=external_conversation_id,
                conversation_id=None,
                text="There is no active chat yet. Send a message or use /new.",
            )
            return None

        thread_id = int(conversation["chat_thread_id"])
        deleted_messages = await clear_chat_thread(thread_id)

        if deleted_messages is None:
            await _send_command_reply(
                provider=provider,
                config=config,
                to=external_conversation_id,
                conversation_id=int(conversation["id"]),
                text="The current chat no longer exists. Use /new to start again.",
            )
            return int(conversation["id"])

        await _send_command_reply(
            provider=provider,
            config=config,
            to=external_conversation_id,
            conversation_id=int(conversation["id"]),
            text=(
                f"Cleared chat #{thread_id}."
                if deleted_messages == 0
                else f"Cleared chat #{thread_id} ({deleted_messages} messages)."
            ),
        )
        return int(conversation["id"])

    if command.name == "delete":
        if not conversation:
            await _send_command_reply(
                provider=provider,
                config=config,
                to=external_conversation_id,
                conversation_id=None,
                text="There is no active chat to delete.",
            )
            return None

        thread_id = int(conversation["chat_thread_id"])
        conversation_id = int(conversation["id"])

        await delete_chat_thread(thread_id)
        await delete_conversation(conversation_id)
        await _send_command_reply(
            provider=provider,
            config=config,
            to=external_conversation_id,
            conversation_id=None,
            text=(
                f"Deleted chat #{thread_id}. "
                "Send a message or use /new to start again."
            ),
        )
        return None

    await _send_command_reply(
        provider=provider,
        config=config,
        to=external_conversation_id,
        conversation_id=conversation_id,
        text=COMMAND_HELP,
    )
    return conversation_id


async def _send_command_reply(
    *,
    provider: Any,
    config: dict[str, Any],
    to: str,
    conversation_id: int | None,
    text: str,
) -> None:
    await send_outbound_message(
        provider=provider,
        config=config,
        to=to,
        conversation_id=conversation_id,
        text=text,
    )
