import os
import json
import logging
import asyncio

from pathlib import Path

import httpx
import asyncpg

from fastapi import APIRouter, HTTPException

from app.routers.connection_retry import (
    list_connection_fdw_diagnostics,
    refresh_connection_fdw_cache,
)
from app.routers.constants import (
    STEAMPIPE_DB_PASSWORD,
    STEAMPIPE_HOST,
    STEAMPIPE_PORT,
    STEAMPIPE_RESTART_COMMAND,
    STEAMPIPE_RESTART_TIMEOUT_SECONDS,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCKER_SOCKET = Path("/var/run/docker.sock")

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)


@router.get("/health")
async def health():
    # Try a real authenticated query first; fall back to TCP if password not set yet
    try:
        conn = await asyncpg.connect(
            host=STEAMPIPE_HOST,
            port=STEAMPIPE_PORT,
            database="steampipe",
            user="steampipe",
            password=STEAMPIPE_DB_PASSWORD,
            timeout=3,
        )

        await conn.fetchrow("SELECT 1")
        await conn.close()
        return {"steampipe": "connected"}
    except Exception:
        pass

    # Fallback: plain TCP to confirm the port is at least open
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(STEAMPIPE_HOST, STEAMPIPE_PORT), timeout=3
        )

        writer.close()
        await writer.wait_closed()
        return {"steampipe": "connected"}
    except Exception:
        return {"steampipe": "disconnected"}


@router.get("/health/fdw")
async def fdw_health():
    service = await health()

    return {
        **service,
        "actions": {
            "cache_refresh_supported": True,
            "restart_supported": DOCKER_SOCKET.exists()
            or bool(STEAMPIPE_RESTART_COMMAND),
        },
        "connections": await list_connection_fdw_diagnostics(),
    }


@router.post("/health/fdw/{connection_id}/refresh")
async def refresh_fdw(connection_id: int):
    result = await refresh_connection_fdw_cache(connection_id)

    return {
        "ok": True,
        **result,
    }


@router.post("/health/steampipe/restart")
async def restart_steampipe():
    # Prefer Docker socket.
    if DOCKER_SOCKET.exists():
        return await _restart_via_docker_socket()

    # Fallback: configurable shell command for non Docker deployments.
    if not STEAMPIPE_RESTART_COMMAND:
        raise HTTPException(
            status_code=501,
            detail=(
                "Steampipe restart is not configured. "
                "Mount /var/run/docker.sock into the app container or set "
                "STEAMPIPE_RESTART_COMMAND."
            ),
        )

    process = await asyncio.create_subprocess_shell(
        STEAMPIPE_RESTART_COMMAND,
        cwd=str(REPO_ROOT if REPO_ROOT.exists() else Path.cwd()),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=os.environ.copy(),
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=STEAMPIPE_RESTART_TIMEOUT_SECONDS,
        )
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        raise HTTPException(
            status_code=504,
            detail=(
                f"Steampipe restart command timed out after "
                f"{STEAMPIPE_RESTART_TIMEOUT_SECONDS} seconds."
            ),
        ) from exc

    output_parts = [
        stdout.decode("utf-8", errors="replace").strip(),
        stderr.decode("utf-8", errors="replace").strip(),
    ]
    output = "\n".join(part for part in output_parts if part).strip()

    if process.returncode != 0:
        logger.warning(
            "Steampipe restart command failed returncode=%s output=%s",
            process.returncode,
            output,
        )
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Steampipe restart command failed.",
                "operation": "steampipe_restart",
                "error": output or f"Exit code {process.returncode}",
                "retryable": False,
            },
        )

    return {"ok": True, "restart_supported": True, "output": output[:4000]}


async def _restart_via_docker_socket(
    compose_service: str = "steampipe",
) -> dict:
    transport = httpx.AsyncHTTPTransport(uds=str(DOCKER_SOCKET))

    try:
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://docker",
            timeout=10,
        ) as client:
            list_resp = await client.get(
                "/containers/json",
                params={
                    "filters": json.dumps(
                        {"label": [f"com.docker.compose.service={compose_service}"]}
                    )
                },
            )
            list_resp.raise_for_status()
            containers = list_resp.json()

            if not containers:
                raise HTTPException(
                    status_code=404,
                    detail=f"No running container found for compose service '{compose_service}'.",
                )

            container_id = containers[0]["Id"]
            short_id = container_id[:12]
            restart_resp = await client.post(
                f"/containers/{container_id}/restart",
                timeout=STEAMPIPE_RESTART_TIMEOUT_SECONDS,
            )

            restart_resp.raise_for_status()

    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Docker socket restart failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Docker socket restart failed.",
                "operation": "steampipe_restart",
                "error": f"{exc.__class__.__name__}: {exc}",
                "retryable": False,
            },
        ) from exc

    return {
        "ok": True,
        "restart_supported": True,
        "output": f"Container {short_id} restarted.",
    }
