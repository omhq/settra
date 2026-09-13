from typing import Any

from fastapi import APIRouter, Body

from app.cube.query import execute_cube_query_payload
from app.semantic.catalog import organization_cube_names

router = APIRouter(prefix="/query", tags=["query"])


@router.post("/")
async def run_query(body: Any = Body(...)) -> dict[str, Any]:
    return await execute_cube_query_payload(
        body,
        allowed_names=await organization_cube_names(),
    )
