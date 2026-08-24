import os

from fastapi import APIRouter, Request, Response

from app.auth import current_identity
from app.common.product import AI_CLIENT_DESCRIPTION, PRODUCT_NAME
from app.routers.oauth import oauth_enabled

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/product")
async def product_settings(response: Response):
    _disable_cache(response)
    return {"product_name": PRODUCT_NAME}


@router.get("")
async def deployment_settings(request: Request, response: Response):
    _disable_cache(response)

    public_url = _public_origin(request)
    identity = current_identity()

    return {
        "product_name": PRODUCT_NAME,
        "public_url": public_url,
        "mcp_url": f"{public_url}/mcp",
        "ai_client_description": AI_CLIENT_DESCRIPTION,
        "oauth": {
            "enabled": oauth_enabled(),
            "authorization_identity": identity.email,
        },
        "organization": {
            "id": identity.organization_id,
            "name": identity.organization_name,
            "slug": identity.organization_slug,
        },
    }


def _disable_cache(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


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
