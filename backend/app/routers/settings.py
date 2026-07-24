import os

from fastapi import APIRouter, Request, Response

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("")
async def deployment_settings(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"

    public_url = _public_origin(request)
    oauth_enabled = _boolean_env("SETTRA_OAUTH_ENABLED", default=False)
    oauth_username = (
        os.getenv("SETTRA_OAUTH_ADMIN_USER")
        or os.getenv("BASIC_AUTH_USER")
        or "settra"
    )
    oauth_password = (
        os.getenv("SETTRA_OAUTH_ADMIN_PASSWORD")
        or os.getenv("BASIC_AUTH_PASSWORD")
        or ""
    )
    basic_auth_username = os.getenv("BASIC_AUTH_USER", "").strip()
    basic_auth_password = os.getenv("BASIC_AUTH_PASSWORD", "")

    return {
        "settra_url": public_url,
        "mcp_url": f"{public_url}/mcp",
        "basic_auth": {
            "username": basic_auth_username
            or (oauth_username if oauth_enabled else ""),
            "password": basic_auth_password
            or (oauth_password if oauth_enabled else ""),
        },
        "oauth": {
            "enabled": oauth_enabled,
            "username": oauth_username,
            "password": oauth_password,
        },
    }


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


def _boolean_env(name: str, default: bool) -> bool:
    value = os.getenv(name)

    if value is None:
        return default

    return value.strip().lower() in {"1", "true", "yes", "on"}
