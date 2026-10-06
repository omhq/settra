import asyncio
import unittest

from starlette.requests import Request

from app.auth import Identity, reset_current_identity, set_current_identity
from app.change_events import WorkspaceChangeBroker, workspace_change_broker
from app.routers.events import _sse_event, workspace_events


class WorkspaceChangeBrokerTests(unittest.IsolatedAsyncioTestCase):
    async def test_events_are_scoped_to_one_organization(self):
        broker = WorkspaceChangeBroker()

        async with (
            broker.subscribe(7) as organization_seven,
            broker.subscribe(8) as organization_eight,
        ):
            published = broker.publish(
                organization_id=7,
                resources=("artifacts",),
                action="created",
                entity_id=42,
                artifact_id=42,
            )

            self.assertEqual(published, organization_seven.get_nowait())
            self.assertTrue(organization_eight.empty())

    async def test_slow_subscribers_receive_the_latest_change(self):
        broker = WorkspaceChangeBroker(queue_size=1)

        async with broker.subscribe(7) as queue:
            broker.publish(
                organization_id=7,
                resources=("connections",),
                action="sync_started",
                connection_id=1,
            )
            latest = broker.publish(
                organization_id=7,
                resources=("connections", "semantic_models"),
                action="sync_completed",
                connection_id=1,
            )

            delivered = queue.get_nowait()
            self.assertEqual(latest.id, delivered.id)
            self.assertEqual(("*",), delivered.resources)
            self.assertEqual("resync", delivered.action)
            self.assertTrue(queue.empty())

    async def test_sse_projection_keeps_the_shared_event_envelope(self):
        broker = WorkspaceChangeBroker()
        event = broker.publish(
            organization_id=7,
            resources=("artifact_graphs",),
            action="updated",
            artifact_id=12,
            revision=3,
        )

        rendered = _sse_event(event)

        self.assertIn(f"id: {event.id}\n", rendered)
        self.assertIn("event: workspace-change\n", rendered)
        self.assertIn('"organization_id":7', rendered)
        self.assertIn('"resources":["artifact_graphs"]', rendered)
        self.assertIn('"revision":3', rendered)

    async def test_sse_subscribes_before_announcing_that_it_is_ready(self):
        identity = Identity(
            user_id=3,
            organization_id=7,
            email="owner@example.com",
            display_name="Owner",
            organization_name="Workspace",
            organization_slug="workspace",
            organization_kind="personal",
            role="owner",
        )
        identity_token = set_current_identity(identity)

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        request = Request(
            {"type": "http", "method": "GET", "path": "/api/events"},
            receive,
        )
        response = await workspace_events(request)
        stream = response.body_iterator

        try:
            ready = await anext(stream)
            workspace_change_broker.publish(
                organization_id=7,
                resources=("artifacts",),
                action="updated",
                artifact_id=9,
            )
            changed = await asyncio.wait_for(anext(stream), timeout=0.2)
        finally:
            await stream.aclose()
            reset_current_identity(identity_token)

        self.assertIn("event: ready", ready)
        self.assertIn("event: workspace-change", changed)
        self.assertIn('"artifact_id":9', changed)


if __name__ == "__main__":
    unittest.main()
