from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.auth import require_organization_write_access

from app.collection_build_service import (
    collection_model_file,
    collection_models,
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
    list_artifacts,
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
    ArtifactGraphExecuteRequest,
    ArtifactGraphParameterOptionsRequest,
    ArtifactGraphValidateRequest,
    ArtifactCreate,
    ArtifactGraphUpdate,
    ArtifactUpdate,
)

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


class OverlayDocument(BaseModel):
    path: str
    content: str
    create: bool = False
    expected_content: str | None = None
    test_queries: list[dict[str, Any]] | None = None


@router.get("/{artifact_id}/graph")
async def artifact_graph_get(artifact_id: int):
    return await get_collection_graph(artifact_id)


@router.put("/{artifact_id}/graph")
async def artifact_graph_update(artifact_id: int, data: ArtifactGraphUpdate):
    return await save_collection_graph(
        artifact_id,
        content=data.content,
        layout=data.layout,
        expected_revision=data.expected_revision,
    )


@router.post("/{artifact_id}/graph/validate")
async def artifact_graph_validate(
    artifact_id: int,
    data: ArtifactGraphValidateRequest,
):
    graph = await get_collection_graph(artifact_id)
    return await validate_collection_graph(
        artifact_id,
        content=data.content if data.content is not None else str(graph["content"]),
        target_node_id=data.target_node_id,
    )


@router.post("/{artifact_id}/graph/execute")
async def artifact_graph_execute(
    artifact_id: int,
    data: ArtifactGraphExecuteRequest,
):
    graph = await get_collection_graph(artifact_id)
    return await execute_collection_graph(
        artifact_id,
        content=data.content if data.content is not None else str(graph["content"]),
        target_node_id=data.target_node_id,
        parameters=data.parameters,
    )


@router.post("/{artifact_id}/graph/parameters/{parameter_id}/options")
async def artifact_graph_parameter_option_list(
    artifact_id: int,
    parameter_id: str,
    data: ArtifactGraphParameterOptionsRequest,
):
    graph = await get_collection_graph(artifact_id)
    return await collection_graph_parameter_options(
        artifact_id,
        parameter_id,
        content=data.content if data.content is not None else str(graph["content"]),
        search=data.search,
    )


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


@router.post("/{artifact_id}/query")
async def artifact_query(artifact_id: int, data: dict[str, Any]):
    return await execute_collection_query(artifact_id, data)


@router.post("/{artifact_id}/pipes/{pipe_id}/tables/{table_name}/sample")
async def artifact_table_sample(
    artifact_id: int, pipe_id: int, table_name: str, data: TableSampleRequest
):
    collection = await get_collection(artifact_id)

    await require_pipe_in_collection(collection["slug"], pipe_id)

    result = await sample_connection_table(
        pipe_id, table_name, limit=data.limit, columns=data.columns
    )

    return semantic_response_projector.table_sample(
        TableSampleProjectionInput(response=result)
    )


@router.post("/{artifact_id}/pipes/{pipe_id}/tables/{table_name}/profile")
async def artifact_table_profile(
    artifact_id: int, pipe_id: int, table_name: str, data: TableProfileRequest
):
    collection = await get_collection(artifact_id)

    await require_pipe_in_collection(collection["slug"], pipe_id)

    result = await profile_connection_table(
        pipe_id, table_name, limit=data.limit, columns=data.columns
    )

    return semantic_response_projector.table_profile(
        TableProfileProjectionInput(response=result, include_descriptions=True)
    )


@router.get("/{artifact_id}/models")
async def artifact_model_list(artifact_id: int):
    return await collection_models(artifact_id)


@router.get("/{artifact_id}/impact/model/{file_path:path}")
async def artifact_model_deletion_impact(artifact_id: int, file_path: str):
    return await preview_model_deletion(artifact_id, file_path)


@router.get("/{artifact_id}/impact/source/{pipe_id}")
async def artifact_source_removal_impact(artifact_id: int, pipe_id: int):
    return await preview_source_removal(artifact_id, pipe_id)


@router.post("/{artifact_id}/relationships/draft")
async def artifact_relationship_draft(artifact_id: int, data: RelationshipDraftRequest):
    require_organization_write_access()
    return await relationship_draft(artifact_id, **data.model_dump())


@router.post("/{artifact_id}/overlays/validate")
async def artifact_overlay_validate(artifact_id: int, data: OverlayDocument):
    require_organization_write_access()

    collection = await get_collection(artifact_id)

    return await validate_semantic_overlay_document(
        collection=collection["slug"],
        content=data.content,
        path=data.path,
        test_queries=data.test_queries,
    )


@router.post("/{artifact_id}/overlays")
async def artifact_overlay_write(artifact_id: int, data: OverlayDocument):
    require_organization_write_access()
    return await write_collection_overlay(
        artifact_id,
        path=data.path,
        content=data.content,
        create=data.create,
        expected_content=data.expected_content,
    )


@router.get("/{artifact_id}/models/{file_path:path}")
async def artifact_model_get(artifact_id: int, file_path: str):
    return await collection_model_file(artifact_id, file_path)


@router.delete("/{artifact_id}/overlays/{file_path:path}")
async def artifact_overlay_delete(artifact_id: int, file_path: str):
    require_organization_write_access()
    return await remove_collection_overlay(artifact_id, file_path)


@router.get("")
async def artifact_list():
    return await list_artifacts()


@router.post("", status_code=201)
async def artifact_create(data: ArtifactCreate):
    return await create_collection(
        name=data.name,
        description=data.description,
        agent_instructions=data.agent_instructions,
        pipe_ids=data.pipe_ids,
    )


@router.get("/{artifact_id}")
async def artifact_get(artifact_id: int):
    return await get_collection(artifact_id)


@router.get("/{artifact_id}/relationships")
async def artifact_relationship_list(artifact_id: int):
    return await get_collection_relationships(artifact_id)


@router.post("/{artifact_id}/relationships/validate")
async def artifact_relationship_validate(artifact_id: int):
    return await validate_collection_relationships(artifact_id)


@router.put("/{artifact_id}")
async def artifact_update(artifact_id: int, data: ArtifactUpdate):
    return await update_collection(
        artifact_id,
        name=data.name,
        description=data.description,
        agent_instructions=data.agent_instructions,
        pipe_ids=data.pipe_ids,
    )


@router.delete("/{artifact_id}")
async def artifact_delete(artifact_id: int):
    return await delete_collection(artifact_id)
