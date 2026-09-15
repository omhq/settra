import asyncpg

from fastapi import APIRouter
from app.auth import require_organization_write_access

from app.routers.connection_retry import (
    list_connection_diagnostics,
    refresh_connection_data,
)
from app.common.config import (
    POSTGRES_DATABASE,
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
)

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    try:
        connection = await asyncpg.connect(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            database=POSTGRES_DATABASE,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            timeout=3,
        )
        version = await connection.fetchval("SHOW server_version")
        await connection.close()
        return {
            "postgres": "connected",
            "version": version,
            "destination": {
                "host": POSTGRES_HOST,
                "port": POSTGRES_PORT,
                "database": POSTGRES_DATABASE,
            },
        }
    except Exception as exc:
        return {
            "postgres": "disconnected",
            "error": str(exc),
            "destination": {
                "host": POSTGRES_HOST,
                "port": POSTGRES_PORT,
                "database": POSTGRES_DATABASE,
            },
        }


@router.get("/health/data")
async def loader_health():
    service = await health()
    return {
        **service,
        "actions": {
            "sync_supported": True,
        },
        "connections": await list_connection_diagnostics(),
    }


@router.post("/health/data/{connection_id}/refresh")
async def refresh_loader(connection_id: int):
    require_organization_write_access()
    result = await refresh_connection_data(connection_id)
    return {"ok": True, **result}
