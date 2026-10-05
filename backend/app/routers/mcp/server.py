from .common import RootPathAsSlash, mcp_server

# Importing tool modules registers their decorated handlers on the shared server.
from . import create_semantic_overlay as _create_semantic_overlay
from . import create_artifact as _create_artifact
from . import delete_artifact as _delete_artifact
from . import delete_semantic_overlay as _delete_semantic_overlay
from . import draft_relationship as _draft_relationship
from . import execute_artifact_graph as _execute_artifact_graph
from . import get_artifact_graph as _get_artifact_graph
from . import get_connection_metadata as _get_connection_metadata
from . import get_artifact_context as _get_artifact_context
from . import get_cube as _get_cube
from . import get_cube_meta as _get_cube_meta
from . import get_semantic_overlay as _get_semantic_overlay
from . import list_connections as _list_connections
from . import (
    list_artifact_graph_parameter_options as _list_artifact_graph_parameter_options,
)
from . import list_artifacts as _list_artifacts
from . import list_cubes as _list_cubes
from . import list_relationships as _list_relationships
from . import list_semantic_overlays as _list_semantic_overlays
from . import manage_artifact_graph as _manage_artifact_graph
from . import profile_connection_table as _profile_connection_table
from . import preview_dependency_impact as _preview_dependency_impact
from . import query_cube as _query_cube
from . import resources as _resources
from . import sample_connection_table as _sample_connection_table
from . import sync_connection as _sync_connection
from . import update_semantic_overlay as _update_semantic_overlay
from . import update_artifact as _update_artifact
from . import validate_artifact_graph as _validate_artifact_graph
from . import validate_relationships as _validate_relationships
from . import validate_semantic_overlay as _validate_semantic_overlay

mcp_app = RootPathAsSlash(mcp_server.streamable_http_app())
