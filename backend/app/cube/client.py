import hmac
import json
import time
import asyncio
import base64
import hashlib

from typing import Any

import httpx

from app.cube.config import (
    CUBE_API_SECRET,
    CUBE_API_TIMEOUT_SECONDS,
    CUBE_API_URL,
    CUBE_QUERY_CONTINUE_WAIT_ATTEMPTS,
    CUBE_QUERY_CONTINUE_WAIT_SLEEP_SECONDS,
)


class CubeAPIError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int = 502,
        payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.payload = payload or {}


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


def _cube_headers() -> dict[str, str]:
    headers: dict[str, str] = {}
    token = cube_api_token()

    if token:
        headers["Authorization"] = token

    return headers


def _response_payload(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {"error": response.text}

    return payload if isinstance(payload, dict) else {"raw": payload}


async def _get_cube_json(
    path: str,
    *,
    params: dict[str, str] | None = None,
) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=CUBE_API_TIMEOUT_SECONDS) as client:
            response = await client.get(
                f"{CUBE_API_URL}{path}",
                headers=_cube_headers(),
                params=params,
            )
    except httpx.RequestError as exc:
        raise CubeAPIError(
            f"Could not reach Cube API: {exc}",
            status_code=503,
            payload={"error": str(exc)},
        ) from exc

    payload = _response_payload(response)

    if response.is_error:
        raise CubeAPIError(
            str(payload.get("error") or payload.get("message") or response.text),
            status_code=response.status_code,
            payload=payload,
        )

    return payload


async def load_cube_meta() -> dict[str, Any]:
    return await _get_cube_json("/v1/meta")


async def load_cube_query(
    query: dict[str, Any] | list[dict[str, Any]],
) -> dict[str, Any]:
    query_json = json.dumps(query, separators=(",", ":"))
    last_payload: dict[str, Any] = {}

    for attempt in range(CUBE_QUERY_CONTINUE_WAIT_ATTEMPTS + 1):
        payload = await _get_cube_json("/v1/load", params={"query": query_json})
        last_payload = payload

        if payload.get("error") != "Continue wait":
            return payload

        if attempt < CUBE_QUERY_CONTINUE_WAIT_ATTEMPTS:
            await asyncio.sleep(CUBE_QUERY_CONTINUE_WAIT_SLEEP_SECONDS)

    raise CubeAPIError(
        "Cube query is still running after the configured wait attempts.",
        status_code=504,
        payload=last_payload,
    )
