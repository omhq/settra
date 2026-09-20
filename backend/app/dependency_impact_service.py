from typing import Any

import yaml

from app.auth import current_organization_id
from app.collection_build_service import collection_model_file
from app.collection_graph_service import list_effective_graph_documents
from app.collection_service import (
    collection_overlay_prefix,
    get_collection,
    list_apps,
)
from app.common.config import GOOGLE_DRIVE_KEY
from app.cube.model import model_repository
from app.db import db_connection
from app.errors import ResourceNotFoundError
from app.semantic.catalog import (
    allowed_cube_names_for_pipe_ids,
    authored_definition_index,
    definition_connection_ids,
    definition_dependencies,
    definition_physical_schema,
)
from app.semantic.query import referenced_cube_names


async def preview_model_deletion(
    collection_id: int,
    path: str,
) -> dict[str, Any]:
    owner = await get_collection(collection_id)
    file = await collection_model_file(collection_id, path)
    direct_models = set(file["cube_names"]) | set(file["view_names"])
    target = {"path": file["path"], "models": sorted(direct_models)}
    impacts = []

    for collection in await list_apps():
        visible_names = set(collection["cube_names"])
        visible_direct_models = direct_models & visible_names

        # An owned file remains deletable while it is temporarily invalid or
        # outside the App's current source scope. Preserve that impact here.
        if int(collection["id"]) == int(owner["id"]):
            visible_direct_models = direct_models

        if not visible_direct_models:
            continue

        affected_models = _dependent_model_closure(
            visible_direct_models,
            allowed_names=visible_names | visible_direct_models,
        )
        impacts.append(
            await _collection_impact(
                collection,
                action="delete_model",
                certainty="exact",
                target=target,
                direct_models=visible_direct_models,
                affected_models=affected_models,
            )
        )

    return {
        "action": "delete_model",
        "certainty": "exact",
        "target": target,
        "message": (
            "Deleting this model file makes these App dependencies unavailable."
        ),
        "apps": impacts,
        "summary": _combined_summary(impacts),
        "has_impact": any(item["has_impact"] for item in impacts),
    }


async def preview_source_removal(
    collection_id: int,
    connection_id: int,
    *,
    action: str = "remove_source",
    certainty: str = "exact",
) -> dict[str, Any]:
    collection = await get_collection(collection_id)
    source = next(
        (pipe for pipe in collection["pipes"] if int(pipe["id"]) == int(connection_id)),
        None,
    )

    if source is None:
        raise ResourceNotFoundError("Source is not in this App")

    remaining_ids = {
        int(pipe["id"])
        for pipe in collection["pipes"]
        if int(pipe["id"]) != int(connection_id)
    }
    remaining_namespaces = {
        int(pipe["id"]): str(pipe["destination_schema"])
        for pipe in collection["pipes"]
        if int(pipe["id"]) in remaining_ids
    }
    before = set(collection["cube_names"])
    after = allowed_cube_names_for_pipe_ids(
        remaining_ids,
        pipe_namespaces=remaining_namespaces,
        owned_prefix=collection_overlay_prefix(int(collection["id"])),
    )
    affected_models = before - after
    definitions = authored_definition_index(allowed_names=before)
    direct_models = {
        name
        for name, item in definitions.items()
        if _definition_uses_source(
            item.get("definition"),
            connection_id=int(connection_id),
            destination_schema=str(source["destination_schema"]),
        )
    }

    return await _collection_impact(
        collection,
        action=action,
        certainty=certainty,
        target={
            "connection_id": int(source["id"]),
            "name": source["name"],
            "slug": source["slug"],
        },
        direct_models=direct_models,
        affected_models=affected_models,
        source_identifiers={
            str(source.get("slug") or ""),
            str(source.get("storage_key") or ""),
        }
        - {""},
    )


async def preview_source_schema_change(
    connection_id: int,
    *,
    collection_id: int | None = None,
) -> dict[str, Any]:
    return await _preview_source_across_apps(
        connection_id,
        action="change_source_schema",
        certainty="potential",
        message=(
            "This is a conservative preview. The affected set becomes exact only "
            "after the next source schema is known."
        ),
        collection_id=collection_id,
    )


async def preview_source_deletion(connection_id: int) -> dict[str, Any]:
    return await _preview_source_across_apps(
        connection_id,
        action="delete_source",
        certainty="exact",
        message="Deleting this source makes these App dependencies unavailable.",
        collection_id=None,
    )


async def _preview_source_across_apps(
    connection_id: int,
    *,
    action: str,
    certainty: str,
    message: str,
    collection_id: int | None,
) -> dict[str, Any]:
    source = await _source_record(connection_id)
    collections = (
        [await get_collection(collection_id)]
        if collection_id is not None
        else await list_apps()
    )
    impacts = []

    for collection in collections:
        if connection_id not in {int(value) for value in collection["pipe_ids"]}:
            if collection_id is not None:
                raise ResourceNotFoundError("Source is not in this App")
            continue

        impacts.append(
            await preview_source_removal(
                int(collection["id"]),
                connection_id,
                action=action,
                certainty=certainty,
            )
        )

    return {
        "action": action,
        "certainty": certainty,
        "source": source,
        "message": message,
        "apps": impacts,
        "summary": _combined_summary(impacts),
        "has_impact": any(item["has_impact"] for item in impacts),
    }


async def _collection_impact(
    collection: dict[str, Any],
    *,
    action: str,
    certainty: str,
    target: dict[str, Any],
    direct_models: set[str],
    affected_models: set[str],
    source_identifiers: set[str] | None = None,
) -> dict[str, Any]:
    visible_names = set(collection["cube_names"]) | affected_models
    definitions = authored_definition_index(allowed_names=visible_names)
    kinds = _definition_kinds()
    models = []

    for name in sorted(affected_models):
        item = definitions.get(name, {})
        definition = item.get("definition")
        dependencies = (
            definition_dependencies(definition)
            if isinstance(definition, dict)
            else set()
        )
        models.append(
            {
                "name": name,
                "title": (
                    definition.get("title") or name
                    if isinstance(definition, dict)
                    else name
                ),
                "kind": kinds.get(name, "model"),
                "path": item.get("path"),
                "direct": name in direct_models,
                "depends_on": sorted(dependencies & affected_models),
            }
        )

    relationships = _affected_relationships(definitions, affected_models)
    graph = _affected_graph(
        await list_effective_graph_documents(int(collection["id"])),
        affected_models=affected_models,
        source_identifiers=source_identifiers or set(),
    )
    summary = {
        "model_count": len(models),
        "relationship_count": len(relationships),
        "graph_node_count": len(graph["nodes"]) if graph else 0,
        "graph_output_count": len(graph["outputs"]) if graph else 0,
    }

    return {
        "action": action,
        "certainty": certainty,
        "app": {
            "id": int(collection["id"]),
            "name": collection["name"],
            "slug": collection["slug"],
        },
        "target": target,
        "affected": {
            "models": models,
            "relationships": relationships,
            "graph": graph,
        },
        "summary": summary,
        "has_impact": any(summary.values()),
    }


def _dependent_model_closure(
    direct_models: set[str],
    *,
    allowed_names: set[str],
) -> set[str]:
    definitions = authored_definition_index(allowed_names=allowed_names)
    affected = set(direct_models)
    changed = True

    while changed:
        changed = False

        for name, item in definitions.items():
            definition = item.get("definition")
            if name in affected or not isinstance(definition, dict):
                continue
            if definition_dependencies(definition) & affected:
                affected.add(name)
                changed = True

    return affected


def _definition_uses_source(
    definition: Any,
    *,
    connection_id: int,
    destination_schema: str,
) -> bool:
    if not isinstance(definition, dict):
        return False

    return (
        connection_id in definition_connection_ids(definition)
        or definition_physical_schema(definition) == destination_schema
    )


def _definition_kinds() -> dict[str, str]:
    kinds: dict[str, str] = {}

    for file in model_repository().list_files():
        kinds.update({name: "cube" for name in file["cube_names"]})
        kinds.update({name: "view" for name in file["view_names"]})

    return kinds


def _affected_relationships(
    definitions: dict[str, dict[str, Any]],
    affected_models: set[str],
) -> list[dict[str, Any]]:
    relationships = []

    for source_name, item in sorted(definitions.items()):
        definition = item.get("definition")
        joins = definition.get("joins") if isinstance(definition, dict) else None

        for index, join in enumerate(joins if isinstance(joins, list) else []):
            if not isinstance(join, dict) or not isinstance(join.get("name"), str):
                continue

            target_name = join["name"].strip()

            if (
                source_name not in affected_models
                and target_name not in affected_models
            ):
                continue

            relationships.append(
                {
                    "id": f"{source_name}:{target_name}:{index}",
                    "source_model": source_name,
                    "target_model": target_name,
                    "relationship": join.get("relationship"),
                    "path": item.get("path"),
                }
            )

    return relationships


def _affected_graph(
    documents: list[dict[str, Any]],
    *,
    affected_models: set[str],
    source_identifiers: set[str],
) -> dict[str, Any] | None:
    if not documents:
        return None

    state = _graph_state(
        documents[0],
        affected_models=affected_models,
        source_identifiers=source_identifiers,
    )
    impacted = {
        node_id: set(reasons) for node_id, reasons in state["direct_nodes"].items()
    }
    changed = True
    while changed:
        changed = False
        for node_id, dependencies in state["node_dependencies"].items():
            affected_inputs = sorted(dependencies & set(impacted))
            if affected_inputs and node_id not in impacted:
                impacted[node_id] = {
                    "Depends on affected node(s): " + ", ".join(affected_inputs)
                }
                changed = True

    outputs = {
        output for output, node_id in state["outputs"].items() if node_id in impacted
    }
    reasons = set(state["graph_reasons"])
    if reasons:
        outputs.update(state["outputs"])
    if not impacted and not reasons:
        return None

    return {
        "outputs": sorted(outputs),
        "nodes": [
            {
                "id": node_id,
                "type": state["node_types"].get(node_id, "unknown"),
                "reasons": sorted(node_reasons),
            }
            for node_id, node_reasons in sorted(impacted.items())
        ],
        "reasons": sorted(reasons),
    }


def _graph_state(
    document_record: dict[str, Any],
    *,
    affected_models: set[str],
    source_identifiers: set[str],
) -> dict[str, Any]:
    try:
        document = yaml.safe_load(str(document_record.get("content") or "")) or {}
    except yaml.YAMLError:
        document = {}

    if not isinstance(document, dict):
        document = {}

    raw_nodes = document.get("nodes")
    nodes = {
        str(node["id"]): node
        for node in (raw_nodes if isinstance(raw_nodes, list) else [])
        if isinstance(node, dict) and isinstance(node.get("id"), str)
    }
    direct_nodes: dict[str, set[str]] = {}
    node_dependencies: dict[str, set[str]] = {}

    for node_id, node in nodes.items():
        node_type = node.get("type")

        if node_type == "cube_query":
            query = node.get("query")
            references = (
                referenced_cube_names(query)
                if isinstance(query, (dict, list))
                else set()
            )
            affected = sorted(references & affected_models)

            if affected:
                direct_nodes[node_id] = {
                    "Queries affected model(s): " + ", ".join(affected)
                }
        elif node_type == "aggregate_query":
            source = node.get("source")
            connection = source.get("connection") if isinstance(source, dict) else None

            if isinstance(connection, str) and connection in source_identifiers:
                direct_nodes[node_id] = {"Reads the affected source directly"}
        elif node_type == "formula":
            inputs = node.get("inputs")
            node_dependencies[node_id] = {
                str(value)
                for value in (inputs.values() if isinstance(inputs, dict) else [])
                if isinstance(value, str)
            }
    parameters = document.get("parameters")
    affected_parameters = sorted(
        str(parameter["member"])
        for parameter in (parameters if isinstance(parameters, list) else [])
        if isinstance(parameter, dict)
        and isinstance(parameter.get("member"), str)
        and parameter["member"].split(".", 1)[0] in affected_models
    )
    outputs = document.get("outputs")

    return {
        "direct_nodes": direct_nodes,
        "node_dependencies": node_dependencies,
        "node_types": {
            node_id: str(node.get("type") or "unknown")
            for node_id, node in nodes.items()
        },
        "outputs": {
            str(name): str(node_id)
            for name, node_id in (outputs.items() if isinstance(outputs, dict) else [])
            if isinstance(name, str) and isinstance(node_id, str)
        },
        "graph_reasons": (
            {"Uses affected parameter member(s): " + ", ".join(affected_parameters)}
            if affected_parameters
            else set()
        ),
    }


async def _source_record(connection_id: int) -> dict[str, Any]:
    async with db_connection() as db:
        row = await db.fetchrow(
            """
            SELECT id, name, slug
            FROM connections
            WHERE id = $1 AND organization_id = $2 AND plugin = $3
            """,
            connection_id,
            current_organization_id(),
            GOOGLE_DRIVE_KEY,
        )

    if row is None:
        raise ResourceNotFoundError("Source not found")

    return {"id": int(row["id"]), "name": row["name"], "slug": row["slug"]}


def _combined_summary(impacts: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "app_count": len(impacts),
        "model_count": sum(item["summary"]["model_count"] for item in impacts),
        "relationship_count": sum(
            item["summary"]["relationship_count"] for item in impacts
        ),
        "graph_node_count": sum(
            item["summary"]["graph_node_count"] for item in impacts
        ),
        "graph_output_count": sum(
            item["summary"]["graph_output_count"] for item in impacts
        ),
    }
