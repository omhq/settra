from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.auth import require_organization_write_access

from app.collection_build_service import (
    collection_model_file,
    collection_models,
    collection_overlay_path,
    execute_collection_query,
    relationship_draft,
    remove_collection_overlay,
    write_collection_overlay,
)
from app.semantic.overlay_validation import validate_semantic_overlay_document

from app.collection_service import (
    create_collection,
    delete_collection,
    get_collection,
    list_collections,
    update_collection,
    require_pipe_in_collection,
)
from app.cube.projection import (
    TableSampleProjectionInput,
    TableProfileProjectionInput,
    semantic_response_projector,
)
from app.routers.connection_metadata import (
    sample_connection_table,
    profile_connection_table,
)
from app.relationship_service import (
    get_collection_relationships,
    validate_collection_relationships,
)
from app.schemas import CollectionCreate, CollectionUpdate

router = APIRouter(prefix="/collections", tags=["collections"])


class OverlayDocument(BaseModel):
    path: str
    content: str
    create: bool = False
    expected_content: str | None = None
    test_queries: list[dict[str, Any]] | None = None


class RelationshipDraftRequest(BaseModel):
    source_cube: str
    target_cube: str = ""
    source_member: str = ""
    target_member: str = ""
    relationship: str = "many_to_one"
    source_primary_key: str = ""
    target_primary_key: str = ""
    existing_id: str | None = None
    remove: bool = False


class TableSampleRequest(BaseModel):
    limit: int = Field(default=5, ge=1, le=50)
    columns: list[str] | None = Field(default=None, max_length=24)


class TableProfileRequest(BaseModel):
    limit: int = Field(default=500, ge=1, le=500)
    columns: list[str] | None = Field(default=None, max_length=24)


@router.post("/{collection_id}/query")
async def collection_query(collection_id: int, data: dict[str, Any]):
    return await execute_collection_query(collection_id, data)


@router.post("/{collection_id}/pipes/{pipe_id}/tables/{table_name}/sample")
async def collection_table_sample(
    collection_id: int, pipe_id: int, table_name: str, data: TableSampleRequest
):
    collection = await get_collection(collection_id)

    await require_pipe_in_collection(collection["slug"], pipe_id)

    result = await sample_connection_table(
        pipe_id, table_name, limit=data.limit, columns=data.columns
    )

    return semantic_response_projector.table_sample(
        TableSampleProjectionInput(response=result)
    )


@router.post("/{collection_id}/pipes/{pipe_id}/tables/{table_name}/profile")
async def collection_table_profile(
    collection_id: int, pipe_id: int, table_name: str, data: TableProfileRequest
):
    collection = await get_collection(collection_id)

    await require_pipe_in_collection(collection["slug"], pipe_id)

    result = await profile_connection_table(
        pipe_id, table_name, limit=data.limit, columns=data.columns
    )

    return semantic_response_projector.table_profile(
        TableProfileProjectionInput(response=result, include_descriptions=True)
    )


@router.get("/{collection_id}/models")
async def collection_model_list(collection_id: int):
    return await collection_models(collection_id)


@router.post("/{collection_id}/relationships/draft")
async def collection_relationship_draft(
    collection_id: int, data: RelationshipDraftRequest
):
    require_organization_write_access()
    return await relationship_draft(collection_id, **data.model_dump())


@router.post("/{collection_id}/overlays/validate")
async def collection_overlay_validate(collection_id: int, data: OverlayDocument):
    require_organization_write_access()

    collection = await get_collection(collection_id)
    normalized = collection_overlay_path(data.path)

    return await validate_semantic_overlay_document(
        collection=collection["slug"],
        content=data.content,
        path=normalized,
        test_queries=data.test_queries,
    )


@router.post("/{collection_id}/overlays")
async def collection_overlay_write(collection_id: int, data: OverlayDocument):
    require_organization_write_access()
    return await write_collection_overlay(
        collection_id,
        path=data.path,
        content=data.content,
        create=data.create,
        expected_content=data.expected_content,
    )


@router.get("/{collection_id}/models/{file_path:path}")
async def collection_model_get(collection_id: int, file_path: str):
    return await collection_model_file(collection_id, file_path)


@router.delete("/{collection_id}/overlays/{file_path:path}")
async def collection_overlay_delete(collection_id: int, file_path: str):
    require_organization_write_access()
    return await remove_collection_overlay(collection_id, file_path)


@router.get("")
async def collection_list():
    return await list_collections()


@router.post("", status_code=201)
async def collection_create(data: CollectionCreate):
    return await create_collection(
        name=data.name,
        description=data.description,
        agent_instructions=data.agent_instructions,
        pipe_ids=data.pipe_ids,
    )


@router.get("/{collection_id}")
async def collection_get(collection_id: int):
    return await get_collection(collection_id)


@router.get("/{collection_id}/relationships")
async def collection_relationship_list(collection_id: int):
    return await get_collection_relationships(collection_id)


@router.post("/{collection_id}/relationships/validate")
async def collection_relationship_validate(collection_id: int):
    return await validate_collection_relationships(collection_id)


@router.put("/{collection_id}")
async def collection_update(collection_id: int, data: CollectionUpdate):
    return await update_collection(
        collection_id,
        name=data.name,
        description=data.description,
        agent_instructions=data.agent_instructions,
        pipe_ids=data.pipe_ids,
    )


@router.delete("/{collection_id}")
async def collection_delete(collection_id: int):
    return await delete_collection(collection_id)
