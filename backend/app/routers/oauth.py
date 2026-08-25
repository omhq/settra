import base64
import binascii
import hashlib
import hmac
import html
import json
import os
import secrets
import time
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import asyncpg

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from app.auth import (
    SESSION_COOKIE_NAME,
    Identity,
    authenticate_user,
    identity_for_user_organization,
    load_session,
    organization_identities_for_user,
)
from app.common.product import PRODUCT_NAME
from app.db import db_connection

router = APIRouter(tags=["oauth"])

DEFAULT_SCOPES = ["settra:read", "settra:write"]
READ_SCOPE = "settra:read"
WRITE_SCOPE = "settra:write"
DEFAULT_REDIRECT_HOSTS = ["chatgpt.com"]
DEFAULT_TOKEN_TTL_SECONDS = 60 * 60
DEFAULT_REFRESH_TOKEN_TTL_SECONDS = 30 * 24 * 60 * 60
DEFAULT_CODE_TTL_SECONDS = 5 * 60
SUPPORTED_GRANT_TYPES = ["authorization_code", "refresh_token"]


def oauth_enabled() -> bool:
    return _truthy(os.getenv("MCP_OAUTH_ENABLED", "true"))


def mcp_auth_challenge(request: Request) -> JSONResponse:
    metadata_url = f"{_public_origin(request)}/.well-known/oauth-protected-resource"
    headers = {
        "WWW-Authenticate": (
            f'Bearer resource_metadata="{metadata_url}", ' f'scope="{READ_SCOPE}"'
        )
    }

    return JSONResponse(
        status_code=401,
        content={"detail": "OAuth bearer token required."},
        headers=headers,
    )


async def authorize_mcp_request(request: Request) -> Response | None:
    if request.method == "OPTIONS":
        return None
    if not oauth_enabled():
        return mcp_auth_challenge(request)

    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")

    if scheme.lower() != "bearer" or not token.strip():
        return mcp_auth_challenge(request)

    try:
        claims = _verify_access_token(token.strip(), request)
    except ValueError:
        return mcp_auth_challenge(request)

    granted_scopes = set(str(claims.get("scope", "")).split())

    if READ_SCOPE not in granted_scopes:
        return mcp_auth_challenge(request)

    try:
        user_id = int(claims["sub"])
        organization_id = int(claims["org"])
    except (KeyError, TypeError, ValueError):
        return mcp_auth_challenge(request)

    async with db_connection() as db:
        row = await db.fetchrow(
            """
            SELECT u.email, u.display_name, o.name AS organization_name,
                   o.slug AS organization_slug, o.kind AS organization_kind,
                   m.role
            FROM users u
            JOIN organization_memberships m ON m.user_id = u.id
            JOIN organizations o ON o.id = m.organization_id
            WHERE u.id = $1 AND u.is_active = true AND o.id = $2
            """,
            user_id,
            organization_id,
        )
    if row is None:
        return mcp_auth_challenge(request)

    request.state.identity = Identity(
        user_id=user_id,
        organization_id=organization_id,
        email=str(row["email"]),
        display_name=str(row["display_name"]),
        organization_name=str(row["organization_name"]),
        organization_slug=str(row["organization_slug"]),
        organization_kind=str(row["organization_kind"]),
        role=str(row["role"]),
        oauth_scopes=frozenset(granted_scopes),
    )

    return None


@router.get("/.well-known/oauth-protected-resource")
async def protected_resource_metadata(request: Request) -> dict[str, Any]:
    _require_enabled()
    origin = _public_origin(request)
    return {
        "resource": _resource_identifier(request),
        "authorization_servers": [origin],
        "scopes_supported": _oauth_scopes(),
        "bearer_methods_supported": ["header"],
        "resource_documentation": origin,
    }


@router.get("/.well-known/oauth-authorization-server")
async def oauth_authorization_server_metadata(request: Request) -> dict[str, Any]:
    return _oauth_metadata(request)


@router.get("/.well-known/openid-configuration")
async def openid_configuration(request: Request) -> dict[str, Any]:
    return _oauth_metadata(request)


@router.post("/oauth/register")
async def register_client(request: Request) -> JSONResponse:
    _require_enabled()

    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(400, "Registration body must be JSON") from exc

    if not isinstance(body, dict):
        raise HTTPException(400, "Registration body must be a JSON object")

    redirect_uris = body.get("redirect_uris")

    if not isinstance(redirect_uris, list) or not redirect_uris:
        raise HTTPException(400, "redirect_uris must be a non-empty list")

    redirect_uris = [_as_text(uri) for uri in redirect_uris]

    for uri in redirect_uris:
        _validate_redirect_uri(uri)

    grant_types = _string_list(body.get("grant_types")) or SUPPORTED_GRANT_TYPES
    response_types = _string_list(body.get("response_types")) or ["code"]

    if "authorization_code" not in grant_types:
        raise HTTPException(400, "authorization_code grant is required")

    unsupported_grants = sorted(set(grant_types) - set(SUPPORTED_GRANT_TYPES))

    if unsupported_grants:
        raise HTTPException(
            400,
            f"Unsupported grant types: {', '.join(unsupported_grants)}",
        )
    if "code" not in response_types:
        raise HTTPException(400, "Only code response type is supported")

    grant_types = SUPPORTED_GRANT_TYPES
    response_types = ["code"]
    token_endpoint_auth_method = _as_text(
        body.get("token_endpoint_auth_method", "none")
    )

    if token_endpoint_auth_method != "none":
        raise HTTPException(400, "Only token_endpoint_auth_method none is supported")

    scope = _normalize_scope(body.get("scope"))
    client_name = _as_text(body.get("client_name", f"{PRODUCT_NAME} AI connector"))
    client_id = f"settra_{secrets.token_urlsafe(24)}"

    async with db_connection() as db:
        await db.execute(
            """
            INSERT INTO oauth_clients (
                client_id,
                client_name,
                redirect_uris,
                grant_types,
                response_types,
                scope,
                token_endpoint_auth_method
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            client_id,
            client_name,
            json.dumps(redirect_uris),
            json.dumps(grant_types),
            json.dumps(response_types),
            scope,
            token_endpoint_auth_method,
        )

    return JSONResponse(
        status_code=201,
        content={
            "client_id": client_id,
            "client_id_issued_at": int(time.time()),
            "client_name": client_name,
            "redirect_uris": redirect_uris,
            "grant_types": grant_types,
            "response_types": response_types,
            "scope": scope,
            "token_endpoint_auth_method": token_endpoint_auth_method,
        },
    )


@router.get("/oauth/authorize")
async def authorize_form(request: Request) -> HTMLResponse:
    _require_enabled()
    params = await _validated_authorization_params(request, request.query_params)

    session = await load_session(request.cookies.get(SESSION_COOKIE_NAME, ""))
    if session is not None:
        organizations = await organization_identities_for_user(session.identity.user_id)
        return _render_consent_form(
            request,
            params,
            organizations,
            _new_identity_ticket(session.identity.user_id, params),
            selected_organization_id=session.identity.organization_id,
        )

    return _render_authorize_form(request, params)


@router.post("/oauth/authorize")
async def authorize_submit(request: Request) -> Response:
    _require_enabled()

    form = await request.form()
    params = await _validated_authorization_params(request, form)
    identity_ticket = _as_text(form.get("identity_ticket"))

    if identity_ticket:
        try:
            user_id = _verify_identity_ticket(identity_ticket, params)
            organization_id = int(_as_text(form.get("organization_id")))
        except (TypeError, ValueError):
            return _render_authorize_form(
                request,
                params,
                error="Authorization expired. Sign in again.",
                status_code=400,
            )

        identity = await identity_for_user_organization(user_id, organization_id)
        if identity is None:
            organizations = await organization_identities_for_user(user_id)
            if not organizations:
                return _render_authorize_form(
                    request,
                    params,
                    error="This account no longer belongs to an active workspace.",
                    status_code=403,
                )
            return _render_consent_form(
                request,
                params,
                organizations,
                _new_identity_ticket(user_id, params),
                error="Choose a workspace you can access.",
                status_code=400,
            )

        return await _issue_authorization_code(params, identity)

    username = _as_text(form.get("username"))
    password = _as_text(form.get("password"))
    user = await authenticate_user(username, password)

    if user is None:
        return _render_authorize_form(
            request,
            params,
            error="Invalid username or password.",
            status_code=401,
        )

    organizations = await organization_identities_for_user(user.user_id)
    if not organizations:
        return _render_authorize_form(
            request,
            params,
            error="This account does not belong to an active workspace.",
            status_code=403,
        )

    return _render_consent_form(
        request,
        params,
        organizations,
        _new_identity_ticket(user.user_id, params),
        selected_organization_id=organizations[0].organization_id,
    )


async def _issue_authorization_code(
    params: dict[str, str],
    identity: Identity,
) -> Response:
    granted_scope = _granted_scope(params["scope"], identity)

    code = secrets.token_urlsafe(32)
    expires_at = int(time.time()) + _code_ttl_seconds()

    async with db_connection() as db:
        await db.execute(
            """
            INSERT INTO oauth_authorization_codes (
                code_hash,
                client_id,
                redirect_uri,
                scope,
                resource,
                code_challenge,
                code_challenge_method,
                expires_at,
                user_id,
                organization_id
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            """,
            _hash_secret(code),
            params["client_id"],
            params["redirect_uri"],
            granted_scope,
            params["resource"],
            params["code_challenge"],
            params["code_challenge_method"],
            expires_at,
            identity.user_id,
            identity.organization_id,
        )

    redirect_url = _redirect_with_params(
        params["redirect_uri"],
        {
            "code": code,
            "state": params.get("state", ""),
        },
    )

    return RedirectResponse(redirect_url, status_code=303)


@router.post("/oauth/token")
async def token(request: Request) -> JSONResponse:
    _require_enabled()

    form = await request.form()
    grant_type = _as_text(form.get("grant_type"))

    if grant_type == "authorization_code":
        return await _exchange_authorization_code(request, form)
    if grant_type == "refresh_token":
        return await _exchange_refresh_token(request, form)

    return _token_error(
        "unsupported_grant_type",
        "grant_type must be authorization_code or refresh_token",
    )


async def _exchange_authorization_code(request: Request, form: Any) -> JSONResponse:
    code = _as_text(form.get("code"))
    client_id = _as_text(form.get("client_id"))
    redirect_uri = _as_text(form.get("redirect_uri"))
    code_verifier = _as_text(form.get("code_verifier"))
    resource = _as_text(form.get("resource"))

    if not code or not client_id or not redirect_uri or not code_verifier:
        raise HTTPException(
            400,
            "code, client_id, redirect_uri, and code_verifier are required",
        )

    now = int(time.time())
    refresh_token = _new_refresh_token()
    refresh_family_id = secrets.token_urlsafe(24)

    async with db_connection() as db, db.transaction():
        row = await db.fetchrow(
            """
            SELECT *
            FROM oauth_authorization_codes
            WHERE code_hash = $1
            FOR UPDATE
            """,
            _hash_secret(code),
        )

        if row is None or row["consumed_at"] is not None:
            raise HTTPException(400, "Invalid authorization code")
        if int(row["expires_at"]) < now:
            raise HTTPException(400, "Authorization code expired")
        if row["client_id"] != client_id or row["redirect_uri"] != redirect_uri:
            raise HTTPException(400, "Authorization code mismatch")
        if resource and not _resource_matches(row["resource"], resource):
            raise HTTPException(400, "Invalid resource")
        if not _valid_pkce(row["code_challenge"], code_verifier):
            raise HTTPException(400, "Invalid code_verifier")

        membership_active = await db.fetchval(
            """
            SELECT 1
            FROM users u
            JOIN organization_memberships m ON m.user_id = u.id
            WHERE u.id = $1 AND u.is_active = true AND m.organization_id = $2
            """,
            row["user_id"],
            row["organization_id"],
        )
        if not membership_active:
            raise HTTPException(400, "Account access was revoked")

        await db.execute(
            """
            UPDATE oauth_authorization_codes
            SET consumed_at = now()
            WHERE code_hash = $1
            """,
            _hash_secret(code),
        )
        await _insert_refresh_token(
            db,
            refresh_token=refresh_token,
            family_id=refresh_family_id,
            client_id=client_id,
            scope=row["scope"],
            resource=row["resource"],
            expires_at=now + _refresh_token_ttl_seconds(),
            user_id=int(row["user_id"]),
            organization_id=int(row["organization_id"]),
        )
        await _prune_expired_refresh_tokens(db, now)

    return _token_response(
        request,
        client_id=client_id,
        scope=row["scope"],
        resource=row["resource"],
        refresh_token=refresh_token,
        user_id=int(row["user_id"]),
        organization_id=int(row["organization_id"]),
    )


async def _exchange_refresh_token(request: Request, form: Any) -> JSONResponse:
    presented_token = _as_text(form.get("refresh_token"))
    client_id = _as_text(form.get("client_id"))
    requested_resource = _as_text(form.get("resource"))
    requested_scope = _as_text(form.get("scope"))

    if not presented_token or not client_id:
        return _token_error(
            "invalid_request",
            "refresh_token and client_id are required",
        )

    now = int(time.time())
    replacement_token = _new_refresh_token()

    async with db_connection() as db, db.transaction():
        row = await db.fetchrow(
            """
            SELECT *
            FROM oauth_refresh_tokens
            WHERE token_hash = $1
            FOR UPDATE
            """,
            _hash_secret(presented_token),
        )

        if row is None:
            return _token_error("invalid_grant", "Invalid refresh token")
        if row["client_id"] != client_id:
            return _token_error("invalid_grant", "Refresh token client mismatch")
        if row["consumed_at"] is not None:
            await db.execute(
                """
                UPDATE oauth_refresh_tokens
                SET revoked_at = COALESCE(revoked_at, now())
                WHERE family_id = $1
                """,
                row["family_id"],
            )
            return _token_error(
                "invalid_grant",
                "Refresh token reuse detected; authorization was revoked",
            )
        if row["revoked_at"] is not None or int(row["expires_at"]) <= now:
            return _token_error("invalid_grant", "Refresh token expired or revoked")
        membership_active = await db.fetchval(
            """
            SELECT 1
            FROM users u
            JOIN organization_memberships m ON m.user_id = u.id
            WHERE u.id = $1 AND u.is_active = true AND m.organization_id = $2
            """,
            row["user_id"],
            row["organization_id"],
        )
        if not membership_active:
            return _token_error("invalid_grant", "Account access was revoked")
        if requested_resource and not _resource_matches(
            row["resource"], requested_resource
        ):
            return _token_error("invalid_target", "Invalid resource")

        access_scope = row["scope"]

        if requested_scope:
            requested_scopes = [item for item in requested_scope.split() if item]

            if not set(requested_scopes).issubset(set(row["scope"].split())):
                return _token_error(
                    "invalid_scope",
                    "Requested scope exceeds the originally granted scope",
                )

            access_scope = _scope_string(requested_scopes)

        await db.execute(
            """
            UPDATE oauth_refresh_tokens
            SET consumed_at = now()
            WHERE token_hash = $1
            """,
            row["token_hash"],
        )
        await _insert_refresh_token(
            db,
            refresh_token=replacement_token,
            family_id=row["family_id"],
            client_id=client_id,
            scope=row["scope"],
            resource=row["resource"],
            expires_at=now + _refresh_token_ttl_seconds(),
            user_id=int(row["user_id"]),
            organization_id=int(row["organization_id"]),
        )
        await _prune_expired_refresh_tokens(db, now)

    return _token_response(
        request,
        client_id=client_id,
        scope=access_scope,
        resource=row["resource"],
        refresh_token=replacement_token,
        user_id=int(row["user_id"]),
        organization_id=int(row["organization_id"]),
    )


async def _insert_refresh_token(
    db: asyncpg.Connection,
    *,
    refresh_token: str,
    family_id: str,
    client_id: str,
    scope: str,
    resource: str,
    expires_at: int,
    user_id: int,
    organization_id: int,
) -> None:
    await db.execute(
        """
        INSERT INTO oauth_refresh_tokens (
            token_hash,
            family_id,
            client_id,
            scope,
            resource,
            expires_at,
            user_id,
            organization_id
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """,
        _hash_secret(refresh_token),
        family_id,
        client_id,
        scope,
        resource,
        expires_at,
        user_id,
        organization_id,
    )


async def _prune_expired_refresh_tokens(
    db: asyncpg.Connection,
    now: int,
) -> None:
    await db.execute(
        "DELETE FROM oauth_refresh_tokens WHERE expires_at < $1",
        now,
    )


def _token_response(
    request: Request,
    *,
    client_id: str,
    scope: str,
    resource: str,
    refresh_token: str,
    user_id: int,
    organization_id: int,
) -> JSONResponse:
    now = int(time.time())
    expires_in = _token_ttl_seconds()
    claims = {
        "iss": _public_origin(request),
        "aud": resource,
        "sub": str(user_id),
        "org": str(organization_id),
        "client_id": client_id,
        "scope": scope,
        "iat": now,
        "nbf": now - 5,
        "exp": now + expires_in,
        "jti": secrets.token_urlsafe(16),
    }

    return JSONResponse(
        content={
            "access_token": _sign_jwt(claims),
            "token_type": "Bearer",
            "expires_in": expires_in,
            "scope": scope,
            "refresh_token": refresh_token,
        },
        headers={
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
        },
    )


def _token_error(error: str, description: str) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={
            "error": error,
            "error_description": description,
        },
        headers={
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
        },
    )


def _oauth_metadata(request: Request) -> dict[str, Any]:
    _require_enabled()

    origin = _public_origin(request)

    return {
        "issuer": origin,
        "authorization_endpoint": f"{origin}/oauth/authorize",
        "token_endpoint": f"{origin}/oauth/token",
        "registration_endpoint": f"{origin}/oauth/register",
        "response_types_supported": ["code"],
        "grant_types_supported": SUPPORTED_GRANT_TYPES,
        "token_endpoint_auth_methods_supported": ["none"],
        "code_challenge_methods_supported": ["S256"],
        "scopes_supported": _oauth_scopes(),
        "resource_parameter_supported": True,
    }


async def _validated_authorization_params(
    request: Request,
    values: Any,
) -> dict[str, str]:
    response_type = _as_text(values.get("response_type"))
    client_id = _as_text(values.get("client_id"))
    redirect_uri = _as_text(values.get("redirect_uri"))
    code_challenge = _as_text(values.get("code_challenge"))
    code_challenge_method = _as_text(values.get("code_challenge_method"))
    state = _as_text(values.get("state"))
    scope = _normalize_scope(values.get("scope"))
    expected_resource = _resource_identifier(request)
    resource = _as_text(values.get("resource")) or expected_resource

    if response_type != "code":
        raise HTTPException(400, "response_type must be code")
    if not client_id:
        raise HTTPException(400, "client_id is required")
    if not redirect_uri:
        raise HTTPException(400, "redirect_uri is required")
    if not code_challenge:
        raise HTTPException(400, "code_challenge is required")
    if code_challenge_method != "S256":
        raise HTTPException(400, "code_challenge_method must be S256")
    if not _resource_matches(expected_resource, resource):
        raise HTTPException(400, "Invalid resource")

    client = await _client_by_id(client_id)

    if client is None:
        raise HTTPException(400, "Unknown OAuth client")

    redirect_uris = json.loads(client["redirect_uris"])

    if redirect_uri not in redirect_uris:
        raise HTTPException(400, "redirect_uri is not registered")

    return {
        "response_type": response_type,
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
        "state": state,
        "scope": scope,
        "resource": expected_resource,
    }


async def _client_by_id(client_id: str) -> asyncpg.Record | None:
    async with db_connection() as db:
        return await db.fetchrow(
            """
            SELECT *
            FROM oauth_clients
            WHERE client_id = $1
            """,
            client_id,
        )


def _render_authorize_form(
    request: Request,
    params: dict[str, str],
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    product_name = html.escape(PRODUCT_NAME)
    error_html = f'<p class="error">{html.escape(error)}</p>' if error else ""
    hidden_inputs = "\n".join(
        f'<input type="hidden" name="{html.escape(key)}" '
        f'value="{html.escape(value)}">'
        for key, value in params.items()
        if key != "username"
    )
    action = f"{_public_origin(request)}/oauth/authorize"

    return HTMLResponse(
        status_code=status_code,
        content=f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Connect {product_name}</title>
  <style>
    :root {{
      color-scheme: light dark;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
        "Segoe UI", sans-serif;
    }}
    body {{
      align-items: center;
      background: #f7f8fa;
      color: #17181c;
      display: flex;
      justify-content: center;
      min-height: 100vh;
      margin: 0;
      padding: 24px;
    }}
    main {{
      background: #ffffff;
      border: 1px solid #d9dde5;
      border-radius: 8px;
      box-shadow: 0 16px 60px rgb(17 24 39 / 12%);
      max-width: 420px;
      padding: 28px;
      width: 100%;
    }}
    h1 {{
      font-size: 22px;
      margin: 0 0 8px;
    }}
    p {{
      color: #525866;
      line-height: 1.5;
      margin: 0 0 20px;
    }}
    label {{
      display: block;
      font-size: 13px;
      font-weight: 600;
      margin: 16px 0 6px;
    }}
    input[type="email"], input[type="password"] {{
      border: 1px solid #c8ced8;
      border-radius: 6px;
      box-sizing: border-box;
      font: inherit;
      padding: 10px 12px;
      width: 100%;
    }}
    button {{
      background: #1565c0;
      border: 0;
      border-radius: 6px;
      color: white;
      cursor: pointer;
      font: inherit;
      font-weight: 650;
      margin-top: 22px;
      padding: 11px 14px;
      width: 100%;
    }}
    .error {{
      background: #fff1f1;
      border: 1px solid #ffc9c9;
      border-radius: 6px;
      color: #9f1d1d;
      margin: 0 0 16px;
      padding: 10px 12px;
    }}
  </style>
</head>
<body>
  <main>
    <h1>Connect {product_name}</h1>
    <p>Authorize your AI client to use {product_name}.</p>
    {error_html}
    <form method="post" action="{html.escape(action)}">
      {hidden_inputs}
      <label for="username">Email</label>
      <input id="username" name="username" type="email"
        autocomplete="email" required autofocus>
      <label for="password">Password</label>
      <input id="password" name="password" type="password"
        autocomplete="current-password" required>
      <button type="submit">Continue</button>
    </form>
  </main>
</body>
</html>""",
    )


def _render_consent_form(
    request: Request,
    params: dict[str, str],
    organizations: list[Identity],
    identity_ticket: str,
    *,
    selected_organization_id: int | None = None,
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    product_name = html.escape(PRODUCT_NAME)
    error_html = f'<p class="error">{html.escape(error)}</p>' if error else ""
    hidden_inputs = "\n".join(
        f'<input type="hidden" name="{html.escape(key)}" '
        f'value="{html.escape(value)}">'
        for key, value in params.items()
    )
    organization_options = "\n".join(
        (
            f'<option value="{identity.organization_id}"'
            f'{" selected" if identity.organization_id == selected_organization_id else ""}>'
            f"{html.escape(identity.organization_name)} "
            f"({html.escape(identity.role)})</option>"
        )
        for identity in organizations
    )
    action = f"{_public_origin(request)}/oauth/authorize"
    cancel_url = _redirect_with_params(
        params["redirect_uri"],
        {"error": "access_denied", "state": params.get("state", "")},
    )

    return HTMLResponse(
        status_code=status_code,
        content=f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Connect {product_name}</title>
  <style>
    :root {{ color-scheme: light dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }}
    body {{ align-items: center; background: #f7f8fa; color: #17181c; display: flex;
      justify-content: center; min-height: 100vh; margin: 0; padding: 24px; }}
    main {{ background: #fff; border: 1px solid #d9dde5; border-radius: 8px;
      box-shadow: 0 16px 60px rgb(17 24 39 / 12%); max-width: 460px;
      padding: 28px; width: 100%; }}
    h1 {{ font-size: 22px; margin: 0 0 8px; }}
    p {{ color: #525866; line-height: 1.5; margin: 0 0 20px; }}
    label {{ display: block; font-size: 13px; font-weight: 600; margin: 16px 0 6px; }}
    select {{ border: 1px solid #c8ced8; border-radius: 6px; box-sizing: border-box;
      font: inherit; padding: 10px 12px; width: 100%; }}
    ul {{ color: #525866; line-height: 1.5; padding-left: 22px; }}
    button {{ background: #1565c0; border: 0; border-radius: 6px; color: white;
      cursor: pointer; font: inherit; font-weight: 650; margin-top: 18px;
      padding: 11px 14px; width: 100%; }}
    .cancel {{ color: #525866; display: block; font-size: 14px; margin-top: 14px;
      text-align: center; }}
    .error {{ background: #fff1f1; border: 1px solid #ffc9c9; border-radius: 6px;
      color: #9f1d1d; margin: 0 0 16px; padding: 10px 12px; }}
  </style>
</head>
<body>
  <main>
    <h1>Choose a {product_name} workspace</h1>
    <p>Your authorization will stay pinned to this workspace until you reconnect.</p>
    {error_html}
    <form method="post" action="{html.escape(action)}">
      {hidden_inputs}
      <input type="hidden" name="identity_ticket" value="{html.escape(identity_ticket)}">
      <label for="organization_id">Workspace</label>
      <select id="organization_id" name="organization_id" required>
        {organization_options}
      </select>
      <p style="margin-top: 18px; margin-bottom: 6px; font-weight: 600;">Permissions</p>
      <ul>
        <li>Read synchronized data and semantic metadata.</li>
        <li>Manage semantic overlays only when your workspace role allows it.</li>
      </ul>
      <button type="submit">Allow access</button>
      <a class="cancel" href="{html.escape(cancel_url)}">Cancel</a>
    </form>
  </main>
</body>
</html>""",
    )


def _verify_access_token(token: str, request: Request) -> dict[str, Any]:
    header, claims, signature_input, signature = _split_jwt(token)

    if header.get("alg") != "HS256":
        raise ValueError("Unsupported token algorithm")

    expected = hmac.new(
        _jwt_secret(),
        signature_input.encode("ascii"),
        hashlib.sha256,
    ).digest()

    if not hmac.compare_digest(signature, expected):
        raise ValueError("Invalid token signature")

    now = int(time.time())

    if int(claims.get("exp", 0)) < now:
        raise ValueError("Token expired")
    if int(claims.get("nbf", 0)) > now:
        raise ValueError("Token is not active")
    if claims.get("iss") != _public_origin(request):
        raise ValueError("Invalid token issuer")
    if not _audience_matches(claims.get("aud"), _resource_identifier(request)):
        raise ValueError("Invalid token audience")

    return claims


def _sign_jwt(claims: dict[str, Any]) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    encoded_header = _base64url_json(header)
    encoded_claims = _base64url_json(claims)
    signing_input = f"{encoded_header}.{encoded_claims}"
    signature = hmac.new(
        _jwt_secret(),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()

    return f"{signing_input}.{_base64url_encode(signature)}"


def _new_identity_ticket(user_id: int, params: dict[str, str]) -> str:
    payload = {
        "sub": str(user_id),
        "exp": int(time.time()) + _code_ttl_seconds(),
        "params": _authorization_params_fingerprint(params),
        "nonce": secrets.token_urlsafe(12),
    }
    encoded = _base64url_json(payload)
    signature = hmac.new(
        _jwt_secret(),
        encoded.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{encoded}.{_base64url_encode(signature)}"


def _verify_identity_ticket(ticket: str, params: dict[str, str]) -> int:
    encoded, separator, encoded_signature = ticket.partition(".")
    if not separator:
        raise ValueError("Invalid authorization ticket")

    expected = hmac.new(
        _jwt_secret(),
        encoded.encode("ascii"),
        hashlib.sha256,
    ).digest()
    try:
        signature = _base64url_decode(encoded_signature)
        payload = json.loads(_base64url_decode(encoded))
    except (binascii.Error, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("Invalid authorization ticket") from exc

    if not hmac.compare_digest(signature, expected):
        raise ValueError("Invalid authorization ticket")
    if not isinstance(payload, dict) or int(payload.get("exp", 0)) < int(time.time()):
        raise ValueError("Authorization ticket expired")
    if payload.get("params") != _authorization_params_fingerprint(params):
        raise ValueError("Authorization ticket mismatch")

    return int(payload["sub"])


def _authorization_params_fingerprint(params: dict[str, str]) -> str:
    serialized = json.dumps(params, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _split_jwt(token: str) -> tuple[dict[str, Any], dict[str, Any], str, bytes]:
    parts = token.split(".")

    if len(parts) != 3:
        raise ValueError("Invalid token")

    try:
        header = json.loads(_base64url_decode(parts[0]))
        claims = json.loads(_base64url_decode(parts[1]))
        signature = _base64url_decode(parts[2])
    except (binascii.Error, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("Invalid token") from exc

    if not isinstance(header, dict) or not isinstance(claims, dict):
        raise ValueError("Invalid token")

    return header, claims, f"{parts[0]}.{parts[1]}", signature


def _valid_pkce(code_challenge: str, code_verifier: str) -> bool:
    try:
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    except UnicodeEncodeError:
        return False

    return hmac.compare_digest(code_challenge, _base64url_encode(digest))


def _redirect_with_params(url: str, params: dict[str, str]) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))

    query.update({key: value for key, value in params.items() if value})
    return urlunparse(parsed._replace(query=urlencode(query)))


def _validate_redirect_uri(uri: str) -> None:
    parsed = urlparse(uri)

    # RFC 8252 permits native applications to use an ephemeral HTTP listener on
    # the local loopback interface. Codex Desktop uses this form so the browser
    # can return the authorization code to the app without a hosted callback.
    if (
        parsed.scheme == "http"
        and parsed.hostname in {"127.0.0.1", "::1"}
        and parsed.netloc
    ):
        return

    if parsed.scheme != "https" or not parsed.netloc:
        raise HTTPException(
            400,
            "redirect_uris must be HTTPS URLs or HTTP loopback URLs",
        )
    if not _redirect_host_allowed(parsed.hostname or ""):
        raise HTTPException(
            400,
            f"redirect_uri host is not allowed: {parsed.hostname}",
        )


def _redirect_host_allowed(hostname: str) -> bool:
    hostname = hostname.lower()

    for allowed in _redirect_hosts():
        if allowed.startswith(".") and hostname.endswith(allowed):
            return True
        if hostname == allowed:
            return True
    return False


def _resource_matches(expected: str, supplied: str) -> bool:
    return expected.rstrip("/") == supplied.rstrip("/")


def _audience_matches(audience: Any, expected: str) -> bool:
    if isinstance(audience, str):
        return _resource_matches(expected, audience)
    if isinstance(audience, list):
        return any(
            isinstance(item, str) and _resource_matches(expected, item)
            for item in audience
        )
    return False


def _normalize_scope(scope: Any) -> str:
    requested = _as_text(scope)
    supported = set(_oauth_scopes())

    if not requested:
        return _scope_string(_oauth_scopes())

    scopes = [item for item in requested.split() if item]
    unsupported = sorted(set(scopes) - supported)

    if unsupported:
        raise HTTPException(400, f"Unsupported OAuth scopes: {', '.join(unsupported)}")

    return _scope_string(scopes)


def _granted_scope(requested_scope: str, identity: Identity) -> str:
    scopes = [item for item in requested_scope.split() if item]

    if identity.role not in {"owner", "admin"}:
        scopes = [item for item in scopes if item != WRITE_SCOPE]
    if READ_SCOPE not in scopes:
        raise HTTPException(400, f"{READ_SCOPE} scope is required")

    return _scope_string(scopes)


def _oauth_scopes() -> list[str]:
    configured = [
        item.strip()
        for item in os.getenv("SETTRA_OAUTH_SCOPES", "").replace(",", " ").split()
        if item.strip()
    ]

    return configured or DEFAULT_SCOPES


def _redirect_hosts() -> list[str]:
    configured = [
        item.strip().lower()
        for item in os.getenv("SETTRA_OAUTH_REDIRECT_HOSTS", "").split(",")
        if item.strip()
    ]

    return configured or DEFAULT_REDIRECT_HOSTS


def _public_origin(request: Request) -> str:
    configured = os.getenv("PUBLIC_URL", "").strip()

    if configured:
        return configured.rstrip("/")

    forwarded_proto = request.headers.get("x-forwarded-proto")
    forwarded_host = request.headers.get("x-forwarded-host")
    scheme = (
        forwarded_proto.split(",", 1)[0].strip()
        if forwarded_proto
        else request.url.scheme
    )
    host = (
        forwarded_host.split(",", 1)[0].strip()
        if forwarded_host
        else request.headers.get("host", "")
    )

    return f"{scheme}://{host}".rstrip("/")


def _resource_identifier(request: Request) -> str:
    configured = os.getenv("SETTRA_OAUTH_RESOURCE", "").strip().rstrip("/")

    return configured or _public_origin(request)


def _token_ttl_seconds() -> int:
    return int(os.getenv("MCP_OAUTH_TOKEN_TTL_SECONDS", str(DEFAULT_TOKEN_TTL_SECONDS)))


def _refresh_token_ttl_seconds() -> int:
    return int(
        os.getenv(
            "MCP_OAUTH_REFRESH_TOKEN_TTL_SECONDS",
            str(DEFAULT_REFRESH_TOKEN_TTL_SECONDS),
        )
    )


def _code_ttl_seconds() -> int:
    return int(
        os.getenv("SETTRA_OAUTH_CODE_TTL_SECONDS", str(DEFAULT_CODE_TTL_SECONDS))
    )


def _jwt_secret() -> bytes:
    return os.getenv("SECRET_KEY", "dev-secret-change-me").encode("utf-8")


def _require_enabled() -> None:
    if not oauth_enabled():
        raise HTTPException(404, "OAuth is not enabled")


def _scope_string(scopes: list[str]) -> str:
    return " ".join(dict.fromkeys(scopes))


def _hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def _base64url_json(payload: dict[str, Any]) -> str:
    data = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

    return _base64url_encode(data)


def _base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)

    return base64.urlsafe_b64decode(f"{value}{padding}".encode("ascii"))


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []

    return [_as_text(item) for item in value if isinstance(item, str)]
