import os

from fastapi import APIRouter

router = APIRouter(tags=["config"])


@router.get("/config")
async def get_runtime_config():
    return {
        "public_api_url": _normalize_public_url(
            os.getenv("PUBLIC_API_URL", ""),
        ),
    }


def _normalize_public_url(value: str) -> str:
    return value.strip().rstrip("/")
