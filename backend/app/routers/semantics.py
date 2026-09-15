from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.auth import require_organization_write_access

from app.cube.model import (
    delete_generated_model_file,
    list_model_files,
    read_model_file,
    update_model_file,
    sync_cube_model,
)
from app.collection_service import validate_overlay_for_organization
from app.semantic.catalog import cube_meta, cube_model_summary, organization_cube_names
from app.semantic.overlays import (
    require_complete_overlay_manifest,
    semantic_overlay_write_lock,
    wait_for_compiled_model_names,
    wait_for_removed_model_names,
)

router = APIRouter(prefix="/semantics", tags=["semantics"])


class SaveCubeModelFileRequest(BaseModel):
    content: str
    expected_content: str | None = None


@router.get("/model")
async def get_cube_model() -> dict[str, Any]:
    return await cube_model_summary()


@router.post("/model/sync")
async def sync_model() -> dict[str, Any]:
    require_organization_write_access()
    result = await sync_cube_model()
    allowed_names = await organization_cube_names()
    return {
        "ok": bool(result.get("ok")),
        "model_dir": result.get("model_dir"),
        "files": list_model_files(allowed_names=allowed_names),
    }


@router.get("/model/files")
async def get_cube_model_files() -> dict[str, Any]:
    return {"files": list_model_files(allowed_names=await organization_cube_names())}


@router.get("/model/files/{file_path:path}")
async def get_cube_model_file(file_path: str) -> dict[str, Any]:
    return await _organization_model_file(file_path)


@router.put("/model/files/{file_path:path}")
async def put_cube_model_file(
    file_path: str,
    body: SaveCubeModelFileRequest,
) -> dict[str, Any]:
    require_organization_write_access()

    async with semantic_overlay_write_lock:
        existing = await _organization_model_file(file_path)

        if existing.get("source_type") != "generated_overlay":
            raise HTTPException(400, "Only generated semantic overlays can be edited")
        if (
            body.expected_content is not None
            and existing["content"] != body.expected_content
        ):
            raise HTTPException(
                409, "This model was changed elsewhere. Reload before saving."
            )

        await validate_overlay_for_organization(body.content)

        try:
            require_complete_overlay_manifest(body.content)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

        result = update_model_file(file_path, body.content)
        result.pop("previous_content", None)
        file = result["file"]
        result["cube"] = await wait_for_compiled_model_names(
            [*file["cube_names"], *file["view_names"]]
        )
        removed = set(existing["cube_names"] + existing["view_names"]) - set(
            file["cube_names"] + file["view_names"]
        )

        if removed:
            result["removal"] = await wait_for_removed_model_names(sorted(removed))

        return result


@router.delete("/model/files/{file_path:path}")
async def delete_cube_model_file(file_path: str) -> dict[str, Any]:
    require_organization_write_access()
    async with semantic_overlay_write_lock:
        file = await _organization_model_file(file_path)
        result = delete_generated_model_file(file_path)
        result["cube"] = await wait_for_removed_model_names(
            [*file["cube_names"], *file["view_names"]]
        )

        return result


@router.get("/meta")
async def get_cube_meta() -> dict[str, Any]:
    return await cube_meta()


async def _organization_model_file(file_path: str) -> dict[str, Any]:
    file = read_model_file(file_path)
    allowed_names = await organization_cube_names()
    model_names = set(file.get("cube_names") or []) | set(file.get("view_names") or [])

    if not model_names or not model_names.issubset(allowed_names):
        raise HTTPException(404, "Cube model file not found")

    return file
