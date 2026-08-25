from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, Response

from app.auth import (
    CSRF_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    authenticate_account,
    create_account,
    create_session,
    current_identity,
    delete_session,
    identity_payload,
    registration_enabled,
    secure_cookies,
    session_ttl_seconds,
    switch_session_organization,
)
from app.schemas import AccountLogin, AccountRegister, ActiveOrganizationUpdate
from app.sync.secrets import migrate_legacy_google_oauth_secret

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)


@router.get("/config")
async def auth_config() -> dict:
    return {"registration_enabled": registration_enabled()}


@router.post("/register", status_code=201)
async def register(data: AccountRegister, response: Response) -> dict:
    if not registration_enabled():
        raise HTTPException(403, "Registration is disabled")

    account = await create_account(
        email=data.email,
        display_name=data.display_name,
        password=data.password,
    )
    if account.claimed_legacy_data:
        try:
            await migrate_legacy_google_oauth_secret(account.identity.organization_id)
        except OSError:
            # Account creation is already committed. Keep it usable and let the
            # owner reconnect Google rather than stranding the new account.
            logger.exception("Could not migrate the legacy Google OAuth credential")
    token, csrf_token, expires_at = await create_session(account.identity)
    _set_session_cookies(response, token, csrf_token, expires_at)
    return identity_payload(account.identity)


@router.post("/login")
async def login(data: AccountLogin, response: Response) -> dict:
    identity = await authenticate_account(data.email, data.password)

    if identity is None:
        raise HTTPException(401, "Invalid email or password")

    token, csrf_token, expires_at = await create_session(identity)
    _set_session_cookies(response, token, csrf_token, expires_at)
    return identity_payload(identity)


@router.post("/logout")
async def logout(request: Request, response: Response) -> dict:
    await delete_session(request.cookies.get(SESSION_COOKIE_NAME, ""))
    _clear_session_cookies(response)
    return {"ok": True}


@router.get("/me")
async def me() -> dict:
    return identity_payload(current_identity())


@router.post("/active-organization")
async def change_active_organization(
    data: ActiveOrganizationUpdate,
    request: Request,
) -> dict:
    session = getattr(request.state, "session", None)

    if session is None:
        raise HTTPException(401, "Authentication required")

    identity = await switch_session_organization(
        session.token_hash,
        session.identity.user_id,
        data.organization_id,
    )
    return identity_payload(identity)


def _set_session_cookies(
    response: Response,
    token: str,
    csrf_token: str,
    expires_at: datetime,
) -> None:
    max_age = max(
        0,
        min(
            session_ttl_seconds(),
            int((expires_at - datetime.now(timezone.utc)).total_seconds()),
        ),
    )
    common = {
        "secure": secure_cookies(),
        "samesite": "lax",
        "path": "/",
        "max_age": max_age,
    }
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        httponly=True,
        **common,
    )
    response.set_cookie(
        CSRF_COOKIE_NAME,
        csrf_token,
        httponly=False,
        **common,
    )
    response.headers["Cache-Control"] = "no-store"


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")
    response.headers["Cache-Control"] = "no-store"
