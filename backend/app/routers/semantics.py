from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.cube.model import (
    cube_meta,
    cube_model_summary,
    list_model_files,
    read_model_file,
    save_model_file,
    sync_cube_model,
)

router = APIRouter(prefix="/semantics", tags=["semantics"])


class SaveCubeModelFileRequest(BaseModel):
    content: str


@router.get("/model")
async def get_cube_model() -> dict[str, Any]:
    return await cube_model_summary()


@router.post("/model/sync")
async def sync_model() -> dict[str, Any]:
    return await sync_cube_model()


@router.get("/model/files")
async def get_cube_model_files() -> dict[str, Any]:
    return {"files": list_model_files()}


@router.get("/model/files/{file_path:path}")
async def get_cube_model_file(file_path: str) -> dict[str, Any]:
    return read_model_file(file_path)


@router.put("/model/files/{file_path:path}")
async def put_cube_model_file(
    file_path: str,
    body: SaveCubeModelFileRequest,
) -> dict[str, Any]:
    return save_model_file(file_path, body.content)


@router.get("/meta")
async def get_cube_meta() -> dict[str, Any]:
    return await cube_meta()
