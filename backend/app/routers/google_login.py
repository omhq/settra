import asyncio
import base64
import hashlib
import hmac
import logging
import os
import secrets
import time

from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import id_token as google_id_token

from app.auth import (
    authenticate_or_create_google_account,
    create_session,
    google_login_enabled,
    registration_enabled,
    secure_cookies,
)
from app.routers.auth import set_session_cookies

router = APIRouter(prefix="/auth/google", tags=["auth"])
logger = logging.getLogger(__name__)

GOOGLE_AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
STATE_COOKIE = "settra_google_login_state"
CODE_VERIFIER_COOKIE = "settra_google_login_code_verifier"
STATE_TTL_SECONDS = 10 * 60
SCOPES = ("openid", "email", "profile")


@router.get("/start")
async def start_google_login(request: Request) -> RedirectResponse:
    if not google_login_enabled():
        raise HTTPException(503, "Google login is not enabled")

    nonce = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    timestamp = str(int(time.time()))
    state = f"{timestamp}.{nonce}.{_state_signature(timestamp, nonce)}"
    query = urlencode(
        {
            "client_id": _client_id(),
            "redirect_uri": _redirect_uri(request),
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
            "include_granted_scopes": "false",
        }
    )
    response = RedirectResponse(f"{GOOGLE_AUTHORIZATION_URL}?{query}", status_code=303)
    response.set_cookie(
        STATE_COOKIE,
        state,
        max_age=STATE_TTL_SECONDS,
        httponly=True,
        secure=secure_cookies(),
        samesite="lax",
        path="/api/auth/google/callback",
    )
    response.set_cookie(
        CODE_VERIFIER_COOKIE,
        code_verifier,
        max_age=STATE_TTL_SECONDS,
        httponly=True,
        secure=secure_cookies(),
        samesite="lax",
        path="/api/auth/google/callback",
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/callback")
async def google_login_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    if not google_login_enabled():
        return _redirect_to_frontend("error")

    if error:
        return _redirect_to_frontend("denied")

    cookie_state = request.cookies.get(STATE_COOKIE)
    code_verifier = request.cookies.get(CODE_VERIFIER_COOKIE)
    if (
        not state
        or not cookie_state
        or not code_verifier
        or not hmac.compare_digest(state, cookie_state)
    ):
        return _redirect_to_frontend("error")

    try:
        nonce = _verify_state(state)
        if not code:
            raise HTTPException(400, "Google did not return an authorization code")
        claims = await _exchange_and_verify_code(
            request,
            code,
            nonce,
            code_verifier,
        )
        email = str(claims.get("email") or "")
        if claims.get("email_verified") is not True:
            raise HTTPException(401, "Google email address is not verified")
        fallback_name = email.partition("@")[0]
        display_name = " ".join(str(claims.get("name") or fallback_name).split())
        identity = await authenticate_or_create_google_account(
            subject=str(claims.get("sub") or ""),
            email=email,
            display_name=display_name,
            allow_registration=registration_enabled(),
        )
    except HTTPException as exc:
        logger.warning("Google login failed: %s", exc.detail)
        if exc.status_code == 403 and exc.detail == "Account registration is disabled":
            return _redirect_to_frontend("registration_disabled")
        if exc.status_code == 409:
            return _redirect_to_frontend("account_conflict")
        return _redirect_to_frontend("error")

    token, csrf_token, expires_at = await create_session(identity)
    response = _redirect_to_frontend("connected")
    set_session_cookies(response, token, csrf_token, expires_at)
    return response


async def _exchange_and_verify_code(
    request: Request,
    code: str,
    nonce: str,
    code_verifier: str,
) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            token_response = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": _client_id(),
                    "client_secret": _client_secret(),
                    "redirect_uri": _redirect_uri(request),
                    "grant_type": "authorization_code",
                    "code_verifier": code_verifier,
                },
            )
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Google token exchange failed") from exc

    if token_response.is_error:
        raise HTTPException(502, "Google token exchange failed")

    try:
        token_payload = token_response.json()
    except ValueError as exc:
        raise HTTPException(502, "Google token exchange returned invalid data") from exc
    if not isinstance(token_payload, dict):
        raise HTTPException(502, "Google token exchange returned invalid data")
    raw_id_token = token_payload.get("id_token")
    if not isinstance(raw_id_token, str) or not raw_id_token:
        raise HTTPException(502, "Google did not return an ID token")

    try:
        claims = await asyncio.to_thread(
            google_id_token.verify_oauth2_token,
            raw_id_token,
            GoogleAuthRequest(),
            _client_id(),
        )
    except (ValueError, GoogleAuthError) as exc:
        raise HTTPException(401, "Google ID token verification failed") from exc

    returned_nonce = claims.get("nonce")
    if not isinstance(returned_nonce, str) or not hmac.compare_digest(
        returned_nonce,
        nonce,
    ):
        raise HTTPException(401, "Google login nonce did not match")

    return claims


def _redirect_to_frontend(status: str) -> RedirectResponse:
    path = "/data" if status == "connected" else "/login"
    query = urlencode({"google": status})
    frontend = os.getenv("FRONTEND_URL", "").strip().rstrip("/")

    if not frontend:
        target = f"{path}?{query}"
    else:
        parsed = urlsplit(frontend)
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
                "FRONTEND_URL must be an http(s) origin without a path",
            )
        target = urlunsplit((parsed.scheme, parsed.netloc, path, query, ""))

    response = RedirectResponse(target, status_code=303)
    response.delete_cookie(STATE_COOKIE, path="/api/auth/google/callback")
    response.delete_cookie(CODE_VERIFIER_COOKIE, path="/api/auth/google/callback")
    response.headers["Cache-Control"] = "no-store"
    return response


def _redirect_uri(request: Request) -> str:
    configured = os.getenv("GOOGLE_LOGIN_REDIRECT_URI", "").strip()
    if configured:
        return configured

    origin = os.getenv("PUBLIC_URL", "").strip().rstrip("/")
    if not origin:
        origin = str(request.base_url).rstrip("/")
    return f"{origin}/api/auth/google/callback"


def _client_id() -> str:
    value = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    if not value:
        raise HTTPException(503, "GOOGLE_OAUTH_CLIENT_ID is not configured")
    return value


def _client_secret() -> str:
    value = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
    if not value:
        raise HTTPException(503, "GOOGLE_OAUTH_CLIENT_SECRET is not configured")
    return value


def _state_signature(timestamp: str, nonce: str) -> str:
    digest = hmac.new(
        os.getenv("SECRET_KEY", "dev-secret-change-me").encode("utf-8"),
        f"google-login:{timestamp}:{nonce}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _verify_state(state: str) -> str:
    try:
        timestamp, nonce, signature = state.split(".", 2)
        issued_at = int(timestamp)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "Google login state is invalid") from exc

    now = int(time.time())
    if now - issued_at > STATE_TTL_SECONDS or issued_at > now + 30:
        raise HTTPException(400, "Google login state expired; start again")
    expected = _state_signature(timestamp, nonce)
    if not nonce or not hmac.compare_digest(signature, expected):
        raise HTTPException(400, "Google login state is invalid")
    return nonce
