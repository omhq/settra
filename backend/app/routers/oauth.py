import os
import hmac
import time
import html
import json
import base64
import binascii
import hashlib
import secrets

from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import aiosqlite

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from app.db import DB_PATH

router = APIRouter(tags=["oauth"])

DEFAULT_SCOPES = ["settra:read", "settra:write"]
DEFAULT_REDIRECT_HOSTS = ["chatgpt.com"]
DEFAULT_TOKEN_TTL_SECONDS = 60 * 60
DEFAULT_CODE_TTL_SECONDS = 5 * 60


def oauth_enabled() -> bool:
    return _truthy(os.getenv("SETTRA_OAUTH_ENABLED", "false"))


def mcp_auth_challenge(request: Request) -> JSONResponse:
    metadata_url = f"{_public_origin(request)}/.well-known/oauth-protected-resource"
    headers = {
        "WWW-Authenticate": (
            f'Bearer resource_metadata="{metadata_url}", '
            f'scope="{_scope_string(_oauth_scopes())}"'
        )
    }

    return JSONResponse(
        status_code=401,
        content={"detail": "OAuth bearer token required."},
        headers=headers,
    )


def authorize_mcp_request(request: Request) -> Response | None:
    if request.method == "OPTIONS" or not oauth_enabled():
        return None

    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")

    if scheme.lower() != "bearer" or not token.strip():
        return mcp_auth_challenge(request)

    try:
        claims = _verify_access_token(token.strip(), request)
    except ValueError:
        return mcp_auth_challenge(request)

    granted_scopes = set(str(claims.get("scope", "")).split())

    if not set(_oauth_scopes()).issubset(granted_scopes):
        return mcp_auth_challenge(request)

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

    grant_types = _string_list(body.get("grant_types")) or ["authorization_code"]
    response_types = _string_list(body.get("response_types")) or ["code"]

    if "authorization_code" not in grant_types:
        raise HTTPException(400, "Only authorization_code grant is supported")
    if "code" not in response_types:
        raise HTTPException(400, "Only code response type is supported")

    grant_types = ["authorization_code"]
    response_types = ["code"]
    token_endpoint_auth_method = _as_text(
        body.get("token_endpoint_auth_method", "none")
    )

    if token_endpoint_auth_method != "none":
        raise HTTPException(400, "Only token_endpoint_auth_method none is supported")

    scope = _normalize_scope(body.get("scope"))
    client_name = _as_text(body.get("client_name", "Settra ChatGPT connector"))
    client_id = f"settra_{secrets.token_urlsafe(24)}"

    async with aiosqlite.connect(DB_PATH) as db:
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
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                client_id,
                client_name,
                json.dumps(redirect_uris),
                json.dumps(grant_types),
                json.dumps(response_types),
                scope,
                token_endpoint_auth_method,
            ),
        )
        await db.commit()

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
    return _render_authorize_form(request, params)


@router.post("/oauth/authorize")
async def authorize_submit(request: Request) -> Response:
    _require_enabled()

    form = await request.form()
    params = await _validated_authorization_params(request, form)
    username = _as_text(form.get("username"))
    password = _as_text(form.get("password"))

    if not _valid_admin_credentials(username, password):
        return _render_authorize_form(
            request,
            params,
            error="Invalid username or password.",
            status_code=401,
        )

    code = secrets.token_urlsafe(32)
    expires_at = int(time.time()) + _code_ttl_seconds()

    async with aiosqlite.connect(DB_PATH) as db:
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
                expires_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _hash_secret(code),
                params["client_id"],
                params["redirect_uri"],
                params["scope"],
                params["resource"],
                params["code_challenge"],
                params["code_challenge_method"],
                expires_at,
            ),
        )
        await db.commit()

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

    if _as_text(form.get("grant_type")) != "authorization_code":
        raise HTTPException(400, "Only authorization_code grant is supported")

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

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        row = await (
            await db.execute(
                """
                SELECT *
                FROM oauth_authorization_codes
                WHERE code_hash = ?
                """,
                (_hash_secret(code),),
            )
        ).fetchone()

        if row is None or row["consumed_at"] is not None:
            raise HTTPException(400, "Invalid authorization code")
        if int(row["expires_at"]) < int(time.time()):
            raise HTTPException(400, "Authorization code expired")
        if row["client_id"] != client_id or row["redirect_uri"] != redirect_uri:
            raise HTTPException(400, "Authorization code mismatch")
        if resource and not _resource_matches(row["resource"], resource):
            raise HTTPException(400, "Invalid resource")
        if not _valid_pkce(row["code_challenge"], code_verifier):
            raise HTTPException(400, "Invalid code_verifier")

        await db.execute(
            """
            UPDATE oauth_authorization_codes
            SET consumed_at = datetime('now')
            WHERE code_hash = ?
            """,
            (_hash_secret(code),),
        )
        await db.commit()

    now = int(time.time())
    expires_in = _token_ttl_seconds()
    claims = {
        "iss": _public_origin(request),
        "aud": row["resource"],
        "sub": _oauth_admin_user(),
        "client_id": client_id,
        "scope": row["scope"],
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
            "scope": row["scope"],
        }
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
        "grant_types_supported": ["authorization_code"],
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


async def _client_by_id(client_id: str) -> aiosqlite.Row | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        return await (
            await db.execute(
                """
                SELECT *
                FROM oauth_clients
                WHERE client_id = ?
                """,
                (client_id,),
            )
        ).fetchone()


def _render_authorize_form(
    request: Request,
    params: dict[str, str],
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    username = html.escape(_oauth_admin_user())
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
  <title>Connect Settra</title>
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
    input[type="text"], input[type="password"] {{
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
    <h1>Connect Settra</h1>
    <p>Authorize ChatGPT to use this Settra MCP server.</p>
    {error_html}
    <form method="post" action="{html.escape(action)}">
      {hidden_inputs}
      <label for="username">Username</label>
      <input id="username" name="username" type="text" value="{username}"
        autocomplete="username" required>
      <label for="password">Password</label>
      <input id="password" name="password" type="password"
        autocomplete="current-password" required autofocus>
      <button type="submit">Authorize</button>
    </form>
  </main>
</body>
</html>""",
    )


def _valid_admin_credentials(username: str, password: str) -> bool:
    expected_password = _oauth_admin_password()

    if not expected_password:
        raise HTTPException(500, "SETTRA_OAUTH_ADMIN_PASSWORD is not configured")

    return secrets.compare_digest(
        username,
        _oauth_admin_user(),
    ) and secrets.compare_digest(
        password,
        expected_password,
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

    if parsed.scheme != "https" or not parsed.netloc:
        raise HTTPException(400, "redirect_uris must be HTTPS URLs")
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
    configured = os.getenv("SETTRA_PUBLIC_URL", "").strip()

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


def _oauth_admin_user() -> str:
    return (
        os.getenv("SETTRA_OAUTH_ADMIN_USER") or os.getenv("BASIC_AUTH_USER") or "settra"
    )


def _oauth_admin_password() -> str:
    return (
        os.getenv("SETTRA_OAUTH_ADMIN_PASSWORD")
        or os.getenv("BASIC_AUTH_PASSWORD")
        or ""
    )


def _token_ttl_seconds() -> int:
    return int(
        os.getenv("SETTRA_OAUTH_TOKEN_TTL_SECONDS", str(DEFAULT_TOKEN_TTL_SECONDS))
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
