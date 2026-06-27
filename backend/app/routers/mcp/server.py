from .common import RootPathAsSlash, mcp_server

# Importing tool modules registers their decorated handlers on the shared server.
from . import create_semantic_overlay as _create_semantic_overlay

# Overlay deletion is intentionally a manual admin UI action for now.
from . import get_connection_metadata as _get_connection_metadata
from . import get_cube as _get_cube
from . import get_cube_meta as _get_cube_meta
from . import get_semantic_overlay as _get_semantic_overlay
from . import list_connections as _list_connections
from . import list_cubes as _list_cubes
from . import list_semantic_overlays as _list_semantic_overlays
from . import profile_connection_table as _profile_connection_table
from . import query_cube as _query_cube
from . import resources as _resources
from . import sample_connection_table as _sample_connection_table
from . import save_semantic_overlay as _save_semantic_overlay
from . import update_semantic_overlay as _update_semantic_overlay
from . import validate_semantic_overlay as _validate_semantic_overlay

mcp_app = RootPathAsSlash(mcp_server.streamable_http_app())
