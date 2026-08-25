from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.auth import (
    Identity,
    current_identity,
    identity_for_user_organization,
    normalize_organization_name,
    organization_identities_for_user,
    require_organization_write_access,
)
from app.db import db_connection
from app.schemas import OrganizationUpdate

router = APIRouter(prefix="/organizations", tags=["organizations"])


def _organization_payload(identity: Identity, *, active_id: int) -> dict:
    return {
        "id": identity.organization_id,
        "name": identity.organization_name,
        "slug": identity.organization_slug,
        "kind": identity.organization_kind,
        "role": identity.role,
        "active": identity.organization_id == active_id,
    }


@router.get("")
async def list_organizations() -> dict:
    identity = current_identity()
    organizations = await organization_identities_for_user(identity.user_id)
    return {
        "organizations": [
            _organization_payload(item, active_id=identity.organization_id)
            for item in organizations
        ]
    }


@router.put("/{organization_id}")
async def update_organization(
    organization_id: int,
    data: OrganizationUpdate,
) -> dict:
    identity = require_organization_write_access()

    if organization_id != identity.organization_id:
        raise HTTPException(404, "Workspace not found")

    name = normalize_organization_name(data.name)
    async with db_connection() as db:
        await db.execute(
            """
            UPDATE organizations
            SET name = $1, updated_at = now()
            WHERE id = $2
            """,
            name,
            organization_id,
        )

    updated = await identity_for_user_organization(
        identity.user_id,
        organization_id,
    )
    if updated is None:
        raise HTTPException(404, "Workspace not found")

    return _organization_payload(updated, active_id=organization_id)
