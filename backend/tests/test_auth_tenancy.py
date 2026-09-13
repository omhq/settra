import unittest
from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.auth import (
    Identity,
    SessionIdentity,
    _create_personal_organization,
    _generate_organization_slug,
    hash_password,
    hash_token,
    normalize_organization_name,
    normalize_email,
    reset_current_identity,
    require_organization_write_access,
    set_current_identity,
    valid_csrf,
    verify_password,
)
from app.cube.query import validate_cube_query_names
from app.collection_service import _validate_overlay_storage
from app.semantic.overlays import generated_overlay_path

IDENTITY = Identity(
    user_id=7,
    organization_id=11,
    email="owner@example.com",
    display_name="Owner",
    organization_name="Owner's workspace",
    organization_slug="personal_7",
    organization_kind="personal",
    role="owner",
)


class PasswordTests(unittest.TestCase):
    def test_scrypt_password_round_trip(self):
        encoded = hash_password("correct horse battery staple")

        self.assertTrue(verify_password("correct horse battery staple", encoded))
        self.assertFalse(verify_password("wrong password", encoded))
        self.assertNotIn("correct horse", encoded)

    def test_google_only_account_has_no_local_password(self):
        self.assertFalse(verify_password("any password", None))

    def test_email_is_normalized_and_validated(self):
        self.assertEqual("person@example.com", normalize_email(" Person@Example.COM "))
        with self.assertRaises(HTTPException):
            normalize_email("not-an-email")


class OrganizationSlugTests(unittest.IsolatedAsyncioTestCase):
    def test_slug_uses_readable_words_and_secure_suffix(self):
        with patch(
            "app.auth.secrets.choice",
            side_effect=(
                "optimistic",
                "mindful",
                "otter",
                "k",
                "7",
                "m",
                "4",
                "p",
                "2",
            ),
        ):
            slug = _generate_organization_slug()

        self.assertEqual("optimistic-mindful-otter-k7m4p2", slug)

    async def test_slug_collision_is_retried_inside_the_unique_insert(self):
        db = AsyncMock()
        db.fetchval.side_effect = (None, 42)

        with patch(
            "app.auth._generate_organization_slug",
            side_effect=(
                "calm-clever-otter-234567",
                "bright-swift-falcon-765432",
            ),
        ):
            organization_id, slug = await _create_personal_organization(
                db,
                name="Alex's workspace",
                user_id=7,
            )

        self.assertEqual(42, organization_id)
        self.assertEqual("bright-swift-falcon-765432", slug)
        self.assertEqual(2, db.fetchval.await_count)


class SessionSecurityTests(unittest.TestCase):
    def test_csrf_requires_matching_cookie_header_and_session_hash(self):
        session = SessionIdentity(
            identity=IDENTITY,
            token_hash=hash_token("session"),
            csrf_token_hash=hash_token("csrf"),
            expires_at=datetime.now(timezone.utc),
        )

        self.assertTrue(valid_csrf(session, "csrf", "csrf"))
        self.assertFalse(valid_csrf(session, "csrf", "different"))
        self.assertFalse(valid_csrf(session, "other", "other"))


class TenantBoundaryTests(unittest.TestCase):
    def test_workspace_name_is_normalized_without_global_uniqueness(self):
        self.assertEqual(
            "Acme Workspace",
            normalize_organization_name("  Acme   Workspace "),
        )

        with self.assertRaises(HTTPException):
            normalize_organization_name("   ")

    def test_workspace_write_access_requires_role_and_oauth_scope(self):
        allowed = (
            IDENTITY,
            replace(
                IDENTITY,
                role="admin",
                oauth_scopes=frozenset({"settra:read", "settra:write"}),
            ),
        )
        denied = (
            replace(IDENTITY, role="viewer"),
            replace(
                IDENTITY,
                oauth_scopes=frozenset({"settra:read"}),
            ),
        )

        for identity in allowed:
            token = set_current_identity(identity)
            try:
                self.assertEqual(identity, require_organization_write_access())
            finally:
                reset_current_identity(token)

        for identity in denied:
            token = set_current_identity(identity)
            try:
                with self.assertRaises(HTTPException) as raised:
                    require_organization_write_access()
                self.assertEqual(403, raised.exception.status_code)
            finally:
                reset_current_identity(token)

    def test_cube_queries_cannot_reference_another_tenant_model(self):
        validate_cube_query_names(
            {
                "measures": ["tenant_orders.row_count"],
                "filters": [
                    {
                        "member": "tenant_orders.email",
                        "operator": "equals",
                        "values": ["person@example.com"],
                    }
                ],
            },
            {"tenant_orders"},
        )

        with self.assertRaises(HTTPException) as raised:
            validate_cube_query_names(
                {"measures": ["other_tenant_orders.row_count"]},
                {"tenant_orders"},
            )

        self.assertEqual(404, raised.exception.status_code)

        with self.assertRaises(HTTPException):
            validate_cube_query_names(
                {"order": {"other_tenant_orders.created_at": "desc"}},
                {"tenant_orders"},
            )

    def test_generated_overlay_paths_are_namespaced_by_organization(self):
        token = set_current_identity(IDENTITY)
        try:
            self.assertEqual(
                "overlays/generated/organizations/11/revenue.yaml",
                generated_overlay_path("revenue.yaml"),
            )
            with self.assertRaisesRegex(ValueError, "outside the active organization"):
                generated_overlay_path(
                    "overlays/generated/organizations/12/revenue.yaml"
                )
        finally:
            reset_current_identity(token)

    def test_overlay_sql_is_limited_to_the_tenant_schema(self):
        _validate_overlay_storage(
            {
                "orders": {
                    "sql_table": '"o11_orders"."orders"',
                    "dimensions": [{"name": "email", "sql": "lower(email)"}],
                }
            },
            {"o11_orders"},
        )

        for sql_table in (
            '"o12_orders"."orders"',
            '"o11_orders"."orders" JOIN "o12_orders"."orders" USING (id)',
        ):
            with self.subTest(sql_table=sql_table), self.assertRaises(HTTPException):
                _validate_overlay_storage(
                    {"orders": {"sql_table": sql_table}},
                    {"o11_orders"},
                )

        with self.assertRaises(HTTPException):
            _validate_overlay_storage(
                {
                    "orders": {
                        "sql_table": '"o11_orders"."orders"',
                        "dimensions": [
                            {
                                "name": "server_file",
                                "sql": "pg_read_file('/etc/passwd')",
                            }
                        ],
                    }
                },
                {"o11_orders"},
            )


if __name__ == "__main__":
    unittest.main()
