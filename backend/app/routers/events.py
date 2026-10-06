import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.auth import current_organization_id
from app.change_events import WorkspaceChangeEvent, workspace_change_broker

router = APIRouter(tags=["events"])

HEARTBEAT_SECONDS = 15
MAX_CONNECTION_SECONDS = 300


def _sse_event(event: WorkspaceChangeEvent) -> str:
    return (
        f"id: {event.id}\n"
        "event: workspace-change\n"
        f"data: {json.dumps(event.as_dict(), separators=(',', ':'))}\n\n"
    )


@router.get("/events")
async def workspace_events(request: Request):
    organization_id = current_organization_id()

    async def stream():
        loop = asyncio.get_running_loop()
        reconnect_at = loop.time() + MAX_CONNECTION_SECONDS

        async with workspace_change_broker.subscribe(organization_id) as queue:
            yield "retry: 3000\nevent: ready\ndata: {}\n\n"

            while not await request.is_disconnected():
                remaining = reconnect_at - loop.time()

                if remaining <= 0:
                    return

                try:
                    event = await asyncio.wait_for(
                        queue.get(), timeout=min(HEARTBEAT_SECONDS, remaining)
                    )
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue

                yield _sse_event(event)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
