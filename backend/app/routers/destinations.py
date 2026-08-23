from fastapi import APIRouter

from app.db import db_connection
from app.destinations import public_destination

router = APIRouter(prefix="/destinations", tags=["destinations"])


@router.get("")
async def list_destinations():
    async with db_connection() as db:
        rows = await db.fetch("""
            SELECT id, name, slug, type, configuration,
                   is_builtin, is_default, created_at, updated_at
            FROM destinations
            ORDER BY is_default DESC, name ASC
            """)

    return [public_destination(row) for row in rows]
