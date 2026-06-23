import base64
import hashlib
import hmac
import json
import time

from typing import Any

import httpx

from app.cube.config import CUBE_API_SECRET, CUBE_API_TIMEOUT_SECONDS, CUBE_API_URL


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def cube_api_token() -> str | None:
    if not CUBE_API_SECRET:
        return None

    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"iat": now, "exp": now + 300}
    signing_input = ".".join(
        [
            _base64url(json.dumps(header, separators=(",", ":")).encode("utf-8")),
            _base64url(json.dumps(payload, separators=(",", ":")).encode("utf-8")),
        ]
    )
    signature = hmac.new(
        CUBE_API_SECRET.encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()

    return f"{signing_input}.{_base64url(signature)}"


async def load_cube_meta() -> dict[str, Any]:
    headers: dict[str, str] = {}
    token = cube_api_token()

    if token:
        headers["Authorization"] = token

    async with httpx.AsyncClient(timeout=CUBE_API_TIMEOUT_SECONDS) as client:
        response = await client.get(f"{CUBE_API_URL}/v1/meta", headers=headers)
        response.raise_for_status()
        payload = response.json()

    return payload if isinstance(payload, dict) else {"raw": payload}
