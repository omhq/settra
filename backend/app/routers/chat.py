import uuid

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.chat_jobs import (
    active_chat_jobs_for_thread,
    cancel_chat_job,
    enqueue_chat_job,
    stream_chat_run_events,
)
from app.routers.chat_runner import chat_events, prepare_chat_run, run_chat_once
from app.routers.chat_store import (
    clear_thread_messages,
    delete_thread_record,
    get_thread_detail,
    list_thread_summaries,
)
from app.schemas import ChatRequest
from app.utils import sse_event

router = APIRouter(prefix="/chat", tags=["chat"])


@router.get("/threads")
async def list_threads():
    return await list_thread_summaries()


@router.get("/threads/{thread_id}")
async def get_thread(thread_id: int):
    detail = await get_thread_detail(thread_id)
    detail["runs"] = await active_chat_jobs_for_thread(thread_id)

    return detail


@router.delete("/threads/{thread_id}")
async def delete_thread(thread_id: int):
    await delete_thread_record(thread_id)

    return {"ok": True}


@router.post("/threads/{thread_id}/clear")
async def clear_thread(thread_id: int):
    deleted_messages = await clear_thread_messages(thread_id)

    return {
        "ok": True,
        "thread_id": thread_id,
        "deleted_messages": deleted_messages,
    }


@router.post("/")
async def chat(body: ChatRequest):
    if not body.request_id:
        body.request_id = str(uuid.uuid4())

    prepared = await prepare_chat_run(body)
    request_id = str(body.request_id)
    thread_id = int(prepared["thread_id"])
    await enqueue_chat_job(request_id, thread_id)

    async def stream():
        async for event in stream_chat_run_events(request_id):
            yield sse_event(event)
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/requests/{request_id}/events")
async def chat_request_events(request_id: str):
    async def stream():
        async for event in stream_chat_run_events(request_id):
            yield sse_event(event)
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/requests/{request_id}/cancel")
async def cancel_chat_request(request_id: str):
    return await cancel_chat_job(request_id)
