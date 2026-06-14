from fastapi import APIRouter

from app.schemas import QueryRequest

router = APIRouter(prefix="/query", tags=["query"])


@router.post("/")
async def run_query(body: QueryRequest):
    return {"result": []}
