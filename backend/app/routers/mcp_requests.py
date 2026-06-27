from typing import Annotated, Any

from fastapi import APIRouter, Query

from app.mcp_request_log import mcp_request_page

router = APIRouter(prefix="/requests", tags=["requests"])


@router.get("")
async def get_mcp_requests(
    cursor: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    return await mcp_request_page(cursor=cursor, limit=limit)
