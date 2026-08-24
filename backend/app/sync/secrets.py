from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import aiofiles

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException

from app.auth import current_organization_id
from app.routers.constants import GOOGLE_OAUTH_CREDENTIALS_PATH


def _fernet() -> Fernet:
    secret = os.getenv("SECRET_KEY", "dev-secret-change-me").encode("utf-8")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret).digest())
    return Fernet(key)


def google_oauth_credentials_path(organization_id: int) -> Path:
    organization_id = int(organization_id)
    if organization_id <= 0:
        raise HTTPException(400, "Invalid organization")

    return (
        GOOGLE_OAUTH_CREDENTIALS_PATH.parent
        / "organizations"
        / f"{organization_id}.enc"
    )


async def save_google_oauth_secret(
    secret: dict[str, Any],
    organization_id: int | None = None,
) -> None:
    path = google_oauth_credentials_path(
        organization_id if organization_id is not None else current_organization_id()
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(secret, separators=(",", ":")).encode("utf-8")
    encrypted = _fernet().encrypt(payload)

    async with aiofiles.open(temp_path, "wb") as handle:
        await handle.write(encrypted)

    temp_path.chmod(0o600)
    temp_path.replace(path)


async def load_google_oauth_secret(
    organization_id: int | None = None,
    *,
    required: bool = True,
) -> dict[str, Any]:
    path = google_oauth_credentials_path(
        organization_id if organization_id is not None else current_organization_id()
    )

    if not path.is_file():
        if required:
            raise HTTPException(409, "Connect a Google account before syncing sheets")
        return {}

    try:
        async with aiofiles.open(path, "rb") as handle:
            encrypted = await handle.read()

        payload = _fernet().decrypt(encrypted)
        value = json.loads(payload)
    except (InvalidToken, json.JSONDecodeError) as exc:
        raise HTTPException(
            500,
            "Saved Google OAuth credentials could not be decrypted; reconnect Google",
        ) from exc

    if not isinstance(value, dict) or not value.get("refresh_token"):
        if required:
            raise HTTPException(409, "Reconnect Google before syncing sheets")
        return {}

    return value


def delete_google_oauth_secret(organization_id: int | None = None) -> bool:
    path = google_oauth_credentials_path(
        organization_id if organization_id is not None else current_organization_id()
    )
    existed = path.exists()
    path.unlink(missing_ok=True)
    return existed


async def migrate_legacy_google_oauth_secret(organization_id: int) -> bool:
    """Move the former deployment-wide credential to the first personal tenant."""

    legacy = GOOGLE_OAUTH_CREDENTIALS_PATH
    target = google_oauth_credentials_path(organization_id)

    if target.exists() or not legacy.is_file():
        return False

    target.parent.mkdir(parents=True, exist_ok=True)
    legacy.replace(target)
    target.chmod(0o600)
    return True
