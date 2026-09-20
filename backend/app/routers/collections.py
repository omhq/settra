from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.auth import require_organization_write_access

from app.collection_build_service import (
    collection_model_file,
    collection_models,
    collection_semantic_coverage,
    attach_collection_overlay,
    execute_collection_query,
    relationship_draft,
    remove_collection_overlay,
    write_collection_overlay,
)
from app.collection_graph_service import get_collection_graph, save_collection_graph
from app.calculations.service import (
    collection_graph_parameter_options,
    execute_collection_graph,
    validate_collection_graph,
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
from app.dependency_impact_service import (
    preview_model_deletion,
    preview_source_removal,
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
from app.schemas import (
    AppGraphExecuteRequest,
    AppGraphParameterOptionsRequest,
    AppGraphValidateRequest,
    CollectionCreate,
    CollectionGraphUpdate,
    CollectionUpdate,
)

router = APIRouter(prefix="/apps", tags=["apps"])


class OverlayDocument(BaseModel):
    path: str
    content: str
    create: bool = False
    expected_content: str | None = None
    test_queries: list[dict[str, Any]] | None = None


class AttachOverlayDocument(BaseModel):
    path: str


@router.get("/semantic-coverage")
async def semantic_coverage():
    return await collection_semantic_coverage()


@router.get("/{collection_id}/graph")
async def collection_graph_get(collection_id: int):
    return await get_collection_graph(collection_id)


@router.put("/{collection_id}/graph")
async def collection_graph_update(collection_id: int, data: CollectionGraphUpdate):
    return await save_collection_graph(
        collection_id,
        content=data.content,
        layout=data.layout,
        expected_revision=data.expected_revision,
    )


@router.post("/{collection_id}/graph/validate")
async def collection_graph_validate(
    collection_id: int,
    data: AppGraphValidateRequest,
):
    graph = await get_collection_graph(collection_id)
    return await validate_collection_graph(
        collection_id,
        content=data.content if data.content is not None else str(graph["content"]),
        target_node_id=data.target_node_id,
    )


@router.post("/{collection_id}/graph/execute")
async def collection_graph_execute(
    collection_id: int,
    data: AppGraphExecuteRequest,
):
    graph = await get_collection_graph(collection_id)
    return await execute_collection_graph(
        collection_id,
        content=data.content if data.content is not None else str(graph["content"]),
        target_node_id=data.target_node_id,
        parameters=data.parameters,
    )


@router.post("/{collection_id}/graph/parameters/{parameter_id}/options")
async def collection_graph_parameter_option_list(
    collection_id: int,
    parameter_id: str,
    data: AppGraphParameterOptionsRequest,
):
    graph = await get_collection_graph(collection_id)
    return await collection_graph_parameter_options(
        collection_id,
        parameter_id,
        content=data.content if data.content is not None else str(graph["content"]),
        search=data.search,
    )


@router.post("/{collection_id}/overlays/attach")
async def attach_overlay(collection_id: int, body: AttachOverlayDocument):
    require_organization_write_access()
    return await attach_collection_overlay(collection_id, body.path)


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


@router.get("/{collection_id}/impact/model/{file_path:path}")
async def collection_model_deletion_impact(collection_id: int, file_path: str):
    return await preview_model_deletion(collection_id, file_path)


@router.get("/{collection_id}/impact/source/{pipe_id}")
async def collection_source_removal_impact(collection_id: int, pipe_id: int):
    return await preview_source_removal(collection_id, pipe_id)


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

    return await validate_semantic_overlay_document(
        collection=collection["slug"],
        content=data.content,
        path=data.path,
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
