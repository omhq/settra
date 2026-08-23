from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time

from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.sync.loader import GOOGLE_FILE_SCOPE
from app.sync.secrets import (
    delete_google_oauth_secret,
    load_google_oauth_secret,
    save_google_oauth_secret,
)

router = APIRouter(tags=["google-oauth"])

GOOGLE_AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
STATE_COOKIE = "settra_google_oauth_state"
STATE_TTL_SECONDS = 10 * 60
SCOPES = [
    "openid",
    "email",
    "profile",
    GOOGLE_FILE_SCOPE,
]


@router.get("/google-oauth/status")
async def google_oauth_status(request: Request) -> dict[str, Any]:
    secret = await load_google_oauth_secret(required=False)
    configured = bool(_client_id(required=False) and _client_secret(required=False))
    connected = bool(secret.get("refresh_token"))
    scope_ready = _has_current_google_scope(secret)
    picker_configured = bool(
        _picker_api_key(required=False) and _picker_app_id(required=False)
    )

    return {
        "configured": configured,
        "connected": connected,
        "scope_ready": scope_ready,
        "requires_reconnect": connected and not scope_ready,
        "picker_configured": picker_configured,
        "picker_ready": configured and connected and scope_ready and picker_configured,
        "email": secret.get("email"),
        "name": secret.get("name"),
        "scopes": secret.get("scopes") or [],
        "connected_at": secret.get("connected_at"),
        "redirect_uri": _redirect_uri(request),
        "return_uri": _frontend_return_uri("connected"),
    }


@router.post("/google-oauth/start")
async def start_google_oauth(request: Request) -> JSONResponse:
    client_id = _client_id()
    _client_secret()
    nonce = secrets.token_urlsafe(32)
    timestamp = str(int(time.time()))
    state = f"{timestamp}.{nonce}.{_state_signature(timestamp, nonce)}"
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": _redirect_uri(request),
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "prompt": "consent select_account",
            "include_granted_scopes": "false",
            "state": state,
        }
    )
    response = JSONResponse({"authorization_url": f"{GOOGLE_AUTHORIZATION_URL}?{query}"})
    response.set_cookie(
        STATE_COOKIE,
        state,
        max_age=STATE_TTL_SECONDS,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        path="/api/google-oauth/callback",
    )
    return response


@router.get("/google-oauth/callback")
async def google_oauth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    if error:
        return RedirectResponse(_frontend_return_uri("error"), status_code=303)

    cookie_state = request.cookies.get(STATE_COOKIE)

    if not state or not cookie_state or not hmac.compare_digest(state, cookie_state):
        raise HTTPException(400, "Google OAuth state did not match; start again")

    _verify_state(state)

    if not code:
        raise HTTPException(400, "Google did not return an authorization code")

    async with httpx.AsyncClient(timeout=20) as client:
        token_response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": _client_id(),
                "client_secret": _client_secret(),
                "redirect_uri": _redirect_uri(request),
                "grant_type": "authorization_code",
            },
        )

        if token_response.is_error:
            raise HTTPException(
                502,
                "Google token exchange failed; verify the OAuth client and redirect URI",
            )

        tokens = token_response.json()
        refresh_token = tokens.get("refresh_token")

        if not refresh_token:
            raise HTTPException(
                502,
                "Google did not return a refresh token; revoke Settra access and reconnect",
            )

        profile: dict[str, Any] = {}
        access_token = tokens.get("access_token")

        if access_token:
            profile_response = await client.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if profile_response.is_success:
                profile = profile_response.json()

    await save_google_oauth_secret(
        {
            "refresh_token": refresh_token,
            "email": profile.get("email"),
            "name": profile.get("name"),
            "subject": profile.get("sub"),
            "scopes": str(tokens.get("scope") or "").split(),
            "connected_at": int(time.time()),
        }
    )
    response = RedirectResponse(_frontend_return_uri("connected"), status_code=303)
    response.delete_cookie(STATE_COOKIE, path="/api/google-oauth/callback")
    return response


@router.delete("/google-oauth")
async def disconnect_google_oauth() -> dict[str, Any]:
    return {
        "ok": True,
        "disconnected": delete_google_oauth_secret(),
        "note": "Existing PostgreSQL snapshots remain available; future syncs are disabled.",
    }


@router.post("/google-picker/session")
async def create_google_picker_session() -> JSONResponse:
    secret = await load_google_oauth_secret()

    if not _has_current_google_scope(secret):
        raise HTTPException(
            409,
            "Reconnect Google to grant file-specific Picker access",
        )

    credentials = await _run_sync(lambda: _refresh_google_credentials(secret))
    response = JSONResponse(
        {
            "access_token": credentials.token,
            "expires_at": (
                credentials.expiry.isoformat() if credentials.expiry else None
            ),
            "api_key": _picker_api_key(),
            "app_id": _picker_app_id(),
        }
    )
    response.headers["Cache-Control"] = "no-store"
    return response


def _refresh_google_credentials(secret: dict[str, Any]):
    from dlt.sources.credentials import GcpOAuthCredentials
    from google.auth.transport.requests import Request as GoogleAuthRequest

    credentials = GcpOAuthCredentials(
        client_id=_client_id(),
        client_secret=_client_secret(),
        refresh_token=str(secret["refresh_token"]),
        project_id=os.getenv("GOOGLE_CLOUD_PROJECT") or None,
        scopes=[GOOGLE_FILE_SCOPE],
    ).to_native_credentials()
    credentials.refresh(GoogleAuthRequest())

    if not credentials.token:
        raise HTTPException(502, "Google did not issue a Picker access token")

    return credentials


async def _run_sync(call):
    import asyncio

    return await asyncio.to_thread(call)


def _redirect_uri(request: Request) -> str:
    configured = os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "").strip()

    if configured:
        return configured

    origin = os.getenv("SETTRA_PUBLIC_URL", "").strip().rstrip("/")

    if not origin:
        origin = str(request.base_url).rstrip("/")

    return f"{origin}/api/google-oauth/callback"


def _frontend_return_uri(status: str) -> str:
    configured = os.getenv("SETTRA_FRONTEND_URL", "").strip().rstrip("/")
    query = urlencode({"google": status})

    if not configured:
        return f"/data?{query}"

    parsed = urlsplit(configured)

    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise HTTPException(
            500,
            "SETTRA_FRONTEND_URL must be an http(s) origin without a path",
        )

    return urlunsplit((parsed.scheme, parsed.netloc, "/data", query, ""))


def _client_id(*, required: bool = True) -> str:
    value = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()

    if required and not value:
        raise HTTPException(503, "GOOGLE_OAUTH_CLIENT_ID is not configured")

    return value


def _client_secret(*, required: bool = True) -> str:
    value = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()

    if required and not value:
        raise HTTPException(503, "GOOGLE_OAUTH_CLIENT_SECRET is not configured")

    return value


def _picker_api_key(*, required: bool = True) -> str:
    value = os.getenv("GOOGLE_PICKER_API_KEY", "").strip()

    if required and not value:
        raise HTTPException(503, "GOOGLE_PICKER_API_KEY is not configured")

    return value


def _picker_app_id(*, required: bool = True) -> str:
    value = os.getenv("GOOGLE_PICKER_APP_ID", "").strip()

    if required and not value:
        raise HTTPException(503, "GOOGLE_PICKER_APP_ID is not configured")

    if value and not value.isdigit():
        raise HTTPException(500, "GOOGLE_PICKER_APP_ID must be the numeric project number")

    return value


def _has_current_google_scope(secret: dict[str, Any]) -> bool:
    return GOOGLE_FILE_SCOPE in set(secret.get("scopes") or [])


def _state_signature(timestamp: str, nonce: str) -> str:
    digest = hmac.new(
        os.getenv("SECRET_KEY", "dev-secret-change-me").encode("utf-8"),
        f"google-oauth:{timestamp}:{nonce}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _verify_state(state: str) -> None:
    try:
        timestamp, nonce, signature = state.split(".", 2)
        issued_at = int(timestamp)
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, "Google OAuth state is invalid") from exc

    if int(time.time()) - issued_at > STATE_TTL_SECONDS or issued_at > int(time.time()) + 30:
        raise HTTPException(400, "Google OAuth state expired; start again")

    expected = _state_signature(timestamp, nonce)

    if not hmac.compare_digest(signature, expected):
        raise HTTPException(400, "Google OAuth state is invalid")
