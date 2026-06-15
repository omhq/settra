from typing import Any

from fastapi import APIRouter, Query

from app.routers import semantics_service
from app.semantic.schemas import (
    AiIntrospectRequest,
    CreateMetricRequest,
    CreateRelationshipRequest,
    UpdateMetricRequest,
    UpdateRelationshipRequest,
    UpdateSemanticColumnRequest,
    UpdateSemanticTableRequest,
)

router = APIRouter(prefix="/semantics", tags=["semantics"])


@router.post("/connections/{connection_id}/introspect")
async def introspect_connection(connection_id: int) -> dict[str, Any]:
    return await semantics_service.introspect_connection(connection_id)


@router.post("/ai-introspect")
async def ai_introspect(body: AiIntrospectRequest) -> dict[str, Any]:
    return await semantics_service.ai_introspect(body)


@router.get("/ai-introspect/runs")
async def list_ai_introspection_runs(
    limit: int = Query(default=20, ge=1, le=50),
) -> dict[str, Any]:
    return await semantics_service.list_ai_introspection_runs(limit)


@router.get("/ai-introspect/runs/{run_id}")
async def get_ai_introspection_run(run_id: int) -> dict[str, Any]:
    return await semantics_service.get_ai_introspection_run_by_id(run_id)


@router.get("/connections/{connection_id}")
async def get_connection_semantics(connection_id: int) -> dict[str, Any]:
    return await semantics_service.get_connection_semantics(connection_id)


@router.get("/relationships")
async def list_relationships(
    connection_ids: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> dict[str, Any]:
    return await semantics_service.list_relationships(connection_ids, status)


@router.post("/relationships")
async def create_relationship(body: CreateRelationshipRequest) -> dict[str, Any]:
    return await semantics_service.create_relationship(body)


@router.post("/relationships/{relationship_id}/confirm")
async def confirm_relationship(relationship_id: int) -> dict[str, Any]:
    return await semantics_service.confirm_relationship(relationship_id)


@router.post("/relationships/{relationship_id}/ignore")
async def ignore_relationship(relationship_id: int) -> dict[str, Any]:
    return await semantics_service.ignore_relationship(relationship_id)


@router.patch("/relationships/{relationship_id}")
async def update_relationship(
    relationship_id: int,
    body: UpdateRelationshipRequest,
) -> dict[str, Any]:
    return await semantics_service.update_relationship(relationship_id, body)


@router.delete("/relationships/{relationship_id}")
async def delete_relationship(relationship_id: int) -> dict[str, Any]:
    return await semantics_service.delete_relationship(relationship_id)


@router.patch("/tables/{table_id}")
async def update_semantic_table(
    table_id: int,
    body: UpdateSemanticTableRequest,
) -> dict[str, Any]:
    return await semantics_service.update_semantic_table(table_id, body)


@router.delete("/tables/{table_id}")
async def delete_semantic_table(table_id: int) -> dict[str, Any]:
    return await semantics_service.delete_semantic_table(table_id)


@router.patch("/columns/{column_id}")
async def update_semantic_column(
    column_id: int,
    body: UpdateSemanticColumnRequest,
) -> dict[str, Any]:
    return await semantics_service.update_semantic_column(column_id, body)


@router.delete("/columns/{column_id}")
async def delete_semantic_column(column_id: int) -> dict[str, Any]:
    return await semantics_service.delete_semantic_column(column_id)


@router.post("/metrics")
async def create_metric(body: CreateMetricRequest) -> dict[str, Any]:
    return await semantics_service.create_metric(body)


@router.patch("/metrics/{metric_id}")
async def update_metric(
    metric_id: int,
    body: UpdateMetricRequest,
) -> dict[str, Any]:
    return await semantics_service.update_metric(metric_id, body)


@router.delete("/metrics/{metric_id}")
async def delete_metric(metric_id: int) -> dict[str, Any]:
    return await semantics_service.delete_metric(metric_id)


@router.get("/contract")
async def get_semantic_contract(
    connection_ids: str = Query(..., description="Comma-separated connection ids"),
) -> dict[str, Any]:
    return await semantics_service.get_semantic_contract(connection_ids)


@router.delete("/connections/{connection_id}")
async def delete_connection_semantic_layer(connection_id: int) -> dict[str, Any]:
    return await semantics_service.delete_connection_semantic_layer(connection_id)
