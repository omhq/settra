from __future__ import annotations

import asyncio
import logging

from contextlib import suppress
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.db import db_connection
from app.routers.constants import GOOGLE_DRIVE_KEY
from app.sync.config import read_sync_config
from app.sync.loader import run_connection_sync
from app.sync.secrets import load_google_oauth_secret

logger = logging.getLogger(__name__)


class SyncScheduler:
    def __init__(self, poll_seconds: int = 30) -> None:
        self.poll_seconds = poll_seconds
        self._task: asyncio.Task | None = None
        self._running: set[int] = set()

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="settra-sync-scheduler")

    async def stop(self) -> None:
        if self._task is None:
            return

        self._task.cancel()

        with suppress(asyncio.CancelledError):
            await self._task

        self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await self._schedule_due_connections()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Sync scheduler poll failed")

            await asyncio.sleep(self.poll_seconds)

    async def _schedule_due_connections(self) -> None:
        if not await load_google_oauth_secret(required=False):
            return

        for connection in await _scheduled_connections():
            connection_id = int(connection["id"])

            if connection_id in self._running:
                continue

            config = await read_sync_config(connection["slug"])
            schedule = config.get("load", {}).get("schedule", {}) if config else {}

            if not schedule.get("enabled") or not _is_due(connection, schedule):
                continue

            self._running.add(connection_id)
            task = asyncio.create_task(
                self._run(connection_id),
                name=f"settra-sync-{connection_id}",
            )
            task.add_done_callback(lambda _task: None)

    async def _run(self, connection_id: int) -> None:
        try:
            await run_connection_sync(connection_id, trigger="schedule")
        except Exception:
            logger.exception("Scheduled sync failed connection_id=%s", connection_id)
        finally:
            self._running.discard(connection_id)


async def _scheduled_connections() -> list[dict]:
    async with db_connection() as db:
        rows = await db.fetch(
            """
            SELECT id, slug, status, created_at, last_sync_started_at, last_synced_at
            FROM connections
            WHERE plugin = $1
            ORDER BY id
            """,
            GOOGLE_DRIVE_KEY,
        )
        return [dict(row) for row in rows]


def _is_due(connection: dict, schedule: dict) -> bool:
    from croniter import croniter

    tz = ZoneInfo(str(schedule.get("timezone") or "UTC"))
    base_value = (
        connection.get("last_sync_started_at")
        or connection.get("last_synced_at")
        or connection.get("created_at")
    )
    base = _parse_datetime(base_value).astimezone(tz)
    now = datetime.now(tz)
    return croniter(str(schedule["cron"]), base).get_next(datetime) <= now


def _parse_datetime(value: str | datetime | None) -> datetime:
    if not value:
        return datetime.fromtimestamp(0, timezone.utc)

    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed


sync_scheduler = SyncScheduler()
