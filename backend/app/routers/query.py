from typing import Any

from fastapi import APIRouter, Body

from app.cube.query import execute_cube_query_payload

router = APIRouter(prefix="/query", tags=["query"])


@router.post("/")
async def run_query(body: Any = Body(...)) -> dict[str, Any]:
    return await execute_cube_query_payload(body)
