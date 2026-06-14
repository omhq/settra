import asyncio
import asyncpg

from fastapi import APIRouter

from app.routers.constants import (
    STEAMPIPE_DB_PASSWORD,
    STEAMPIPE_HOST,
    STEAMPIPE_PORT,
)

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    # Try a real authenticated query first; fall back to TCP if password not set yet
    try:
        conn = await asyncpg.connect(
            host=STEAMPIPE_HOST,
            port=STEAMPIPE_PORT,
            database="steampipe",
            user="steampipe",
            password=STEAMPIPE_DB_PASSWORD,
            timeout=3,
        )
        await conn.fetchrow("SELECT 1")
        await conn.close()
        return {"steampipe": "connected"}
    except Exception:
        pass

    # Fallback: plain TCP to confirm the port is at least open
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(STEAMPIPE_HOST, STEAMPIPE_PORT), timeout=3
        )
        writer.close()
        await writer.wait_closed()
        return {"steampipe": "connected"}
    except Exception:
        return {"steampipe": "disconnected"}
