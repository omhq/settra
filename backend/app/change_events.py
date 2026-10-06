import asyncio
import itertools

from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import AsyncGenerator


@dataclass(frozen=True)
class WorkspaceChangeEvent:
    id: int
    organization_id: int
    resources: tuple[str, ...]
    action: str
    entity_id: int | None
    artifact_id: int | None
    connection_id: int | None
    entity_key: str | None
    revision: int | None
    occurred_at: str

    def as_dict(self) -> dict:
        return {
            **asdict(self),
            "resources": list(self.resources),
        }


class WorkspaceChangeBroker:
    """Transport-neutral, organization-scoped workspace change fanout."""

    def __init__(self, *, queue_size: int = 64) -> None:
        self._ids = itertools.count(1)
        self._queue_size = queue_size
        self._subscribers: dict[int, set[asyncio.Queue[WorkspaceChangeEvent]]] = (
            defaultdict(set)
        )

    @asynccontextmanager
    async def subscribe(
        self, organization_id: int
    ) -> AsyncGenerator[asyncio.Queue[WorkspaceChangeEvent], None]:
        queue: asyncio.Queue[WorkspaceChangeEvent] = asyncio.Queue(
            maxsize=self._queue_size
        )
        subscribers = self._subscribers[organization_id]

        subscribers.add(queue)

        try:
            yield queue
        finally:
            subscribers.discard(queue)

            if not subscribers:
                self._subscribers.pop(organization_id, None)

    def publish(
        self,
        *,
        organization_id: int,
        resources: tuple[str, ...],
        action: str,
        entity_id: int | None = None,
        artifact_id: int | None = None,
        connection_id: int | None = None,
        entity_key: str | None = None,
        revision: int | None = None,
    ) -> WorkspaceChangeEvent:
        event = WorkspaceChangeEvent(
            id=next(self._ids),
            organization_id=organization_id,
            resources=tuple(dict.fromkeys(resources)),
            action=action,
            entity_id=entity_id,
            artifact_id=artifact_id,
            connection_id=connection_id,
            entity_key=entity_key,
            revision=revision,
            occurred_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        )

        for queue in tuple(self._subscribers.get(organization_id, ())):
            if queue.full():
                while not queue.empty():
                    queue.get_nowait()

                queue.put_nowait(
                    WorkspaceChangeEvent(
                        id=event.id,
                        organization_id=organization_id,
                        resources=("*",),
                        action="resync",
                        entity_id=None,
                        artifact_id=None,
                        connection_id=None,
                        entity_key=None,
                        revision=None,
                        occurred_at=event.occurred_at,
                    )
                )
            else:
                queue.put_nowait(event)

        return event


workspace_change_broker = WorkspaceChangeBroker()


def publish_workspace_change(
    *,
    organization_id: int,
    resources: tuple[str, ...],
    action: str,
    entity_id: int | None = None,
    artifact_id: int | None = None,
    connection_id: int | None = None,
    entity_key: str | None = None,
    revision: int | None = None,
) -> WorkspaceChangeEvent:
    return workspace_change_broker.publish(
        organization_id=organization_id,
        resources=resources,
        action=action,
        entity_id=entity_id,
        artifact_id=artifact_id,
        connection_id=connection_id,
        entity_key=entity_key,
        revision=revision,
    )
