from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import re
import secrets

from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg
from fastapi import HTTPException

from app.db import db_connection

SESSION_COOKIE_NAME = "settra_session"
CSRF_COOKIE_NAME = "settra_csrf"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
_EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_ORGANIZATION_SLUG_ADJECTIVES = (
    "agile",
    "bright",
    "calm",
    "clever",
    "curious",
    "daring",
    "eager",
    "gentle",
    "happy",
    "kind",
    "lively",
    "lucky",
    "mindful",
    "nimble",
    "optimistic",
    "patient",
    "playful",
    "quiet",
    "radiant",
    "steady",
    "sunny",
    "swift",
    "thoughtful",
    "vibrant",
    "warm",
    "wise",
)
_ORGANIZATION_SLUG_NOUNS = (
    "badger",
    "bear",
    "dolphin",
    "falcon",
    "finch",
    "fox",
    "heron",
    "ibis",
    "koala",
    "lynx",
    "otter",
    "owl",
    "panda",
    "penguin",
    "raven",
    "robin",
    "sparrow",
    "tiger",
    "turtle",
    "whale",
    "wolf",
    "wren",
)
_ORGANIZATION_SLUG_SUFFIX_ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"
_ORGANIZATION_SLUG_SUFFIX_LENGTH = 6
_ORGANIZATION_SLUG_MAX_ATTEMPTS = 8
_identity_context: ContextVar[Identity | None] = ContextVar(
    "settra_identity",
    default=None,
)


@dataclass(frozen=True)
class Identity:
    user_id: int
    organization_id: int
    email: str
    display_name: str
    organization_name: str
    organization_slug: str
    organization_kind: str
    role: str
    oauth_scopes: frozenset[str] | None = None


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: int
    email: str
    display_name: str


@dataclass(frozen=True)
class SessionIdentity:
    identity: Identity
    token_hash: str
    csrf_token_hash: str
    expires_at: datetime


@dataclass(frozen=True)
class CreatedAccount:
    identity: Identity
    claimed_legacy_data: bool


def set_current_identity(identity: Identity) -> Token:
    return _identity_context.set(identity)


def reset_current_identity(token: Token) -> None:
    _identity_context.reset(token)


def current_identity() -> Identity:
    identity = _identity_context.get()

    if identity is None:
        raise HTTPException(401, "Authentication required")

    return identity


def optional_current_identity() -> Identity | None:
    return _identity_context.get()


def current_organization_id() -> int:
    return current_identity().organization_id


def normalize_email(value: str) -> str:
    email = value.strip().lower()

    if len(email) > 320 or not _EMAIL_PATTERN.fullmatch(email):
        raise HTTPException(422, "Enter a valid email address")

    return email


def normalize_display_name(value: str) -> str:
    display_name = " ".join(value.strip().split())

    if not 1 <= len(display_name) <= 120:
        raise HTTPException(422, "Display name must be between 1 and 120 characters")

    return display_name


def validate_password(value: str) -> str:
    if len(value) < 10:
        raise HTTPException(422, "Password must be at least 10 characters")
    if len(value) > 1024:
        raise HTTPException(422, "Password is too long")

    return value


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    cost = 2**14
    block_size = 8
    parallelism = 1
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=cost,
        r=block_size,
        p=parallelism,
        dklen=32,
    )
    return "$".join(
        (
            "scrypt",
            str(cost),
            str(block_size),
            str(parallelism),
            _base64url(salt),
            _base64url(derived),
        )
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, cost, block_size, parallelism, salt, expected = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        expected_bytes = _base64url_decode(expected)
        derived = hashlib.scrypt(
            password.encode("utf-8"),
            salt=_base64url_decode(salt),
            n=int(cost),
            r=int(block_size),
            p=int(parallelism),
            dklen=32,
        )
    except (binascii.Error, ValueError, TypeError):
        return False

    return hmac.compare_digest(derived, expected_bytes)


def _generate_organization_slug() -> str:
    first_adjective = secrets.choice(_ORGANIZATION_SLUG_ADJECTIVES)
    second_adjective = secrets.choice(
        tuple(
            adjective
            for adjective in _ORGANIZATION_SLUG_ADJECTIVES
            if adjective != first_adjective
        )
    )
    noun = secrets.choice(_ORGANIZATION_SLUG_NOUNS)
    suffix = "".join(
        secrets.choice(_ORGANIZATION_SLUG_SUFFIX_ALPHABET)
        for _ in range(_ORGANIZATION_SLUG_SUFFIX_LENGTH)
    )
    return "-".join((first_adjective, second_adjective, noun, suffix))


async def _create_personal_organization(
    db: asyncpg.Connection,
    *,
    name: str,
    user_id: int,
) -> tuple[int, str]:
    for _ in range(_ORGANIZATION_SLUG_MAX_ATTEMPTS):
        slug = _generate_organization_slug()
        organization_id = await db.fetchval(
            """
            INSERT INTO organizations (
                name, slug, kind, personal_owner_user_id
            ) VALUES ($1, $2, 'personal', $3)
            ON CONFLICT (slug) DO NOTHING
            RETURNING id
            """,
            name,
            slug,
            user_id,
        )
        if organization_id is not None:
            return int(organization_id), slug

    raise HTTPException(503, "Could not allocate a unique workspace slug")


async def create_account(
    *,
    email: str,
    display_name: str,
    password: str,
) -> CreatedAccount:
    normalized_email = normalize_email(email)
    normalized_name = normalize_display_name(display_name)
    password_hash = hash_password(validate_password(password))

    try:
        async with db_connection() as db, db.transaction():
            # Serialize registration while deciding which first account claims
            # any deployment data created before accounts existed.
            await db.execute("SELECT pg_advisory_xact_lock($1)", 7_613_202_608_24)
            existing_users = int(await db.fetchval("SELECT COUNT(*) FROM users") or 0)
            user_id = int(
                await db.fetchval(
                    """
                    INSERT INTO users (email, display_name, password_hash)
                    VALUES ($1, $2, $3)
                    RETURNING id
                    """,
                    normalized_email,
                    normalized_name,
                    password_hash,
                )
            )
            organization_name = f"{normalized_name}'s workspace"
            organization_id, organization_slug = await _create_personal_organization(
                db,
                name=organization_name,
                user_id=user_id,
            )
            await db.execute(
                """
                INSERT INTO organization_memberships (organization_id, user_id, role)
                VALUES ($1, $2, 'owner')
                """,
                organization_id,
                user_id,
            )

            claimed_legacy = existing_users == 0
            if claimed_legacy:
                await db.execute(
                    """
                    UPDATE connections
                    SET organization_id = $1,
                        created_by_user_id = COALESCE(created_by_user_id, $2)
                    WHERE organization_id IS NULL
                    """,
                    organization_id,
                    user_id,
                )
                await db.execute(
                    """
                    UPDATE collections
                    SET organization_id = $1,
                        created_by_user_id = COALESCE(created_by_user_id, $2)
                    WHERE organization_id IS NULL
                    """,
                    organization_id,
                    user_id,
                )
                await db.execute(
                    """
                    UPDATE mcp_requests
                    SET organization_id = $1,
                        user_id = COALESCE(user_id, $2)
                    WHERE organization_id IS NULL
                    """,
                    organization_id,
                    user_id,
                )
    except asyncpg.UniqueViolationError as exc:
        raise HTTPException(409, "An account with that email already exists") from exc

    return CreatedAccount(
        identity=Identity(
            user_id=user_id,
            organization_id=organization_id,
            email=normalized_email,
            display_name=normalized_name,
            organization_name=organization_name,
            organization_slug=organization_slug,
            organization_kind="personal",
            role="owner",
        ),
        claimed_legacy_data=claimed_legacy,
    )


async def authenticate_account(email: str, password: str) -> Identity | None:
    user = await authenticate_user(email, password)

    if user is None:
        return None

    organizations = await organization_identities_for_user(user.user_id)

    return organizations[0] if organizations else None


async def authenticate_user(email: str, password: str) -> AuthenticatedUser | None:
    try:
        normalized_email = normalize_email(email)
    except HTTPException:
        return None

    async with db_connection() as db:
        row = await db.fetchrow(
            """
            SELECT u.id AS user_id, u.email, u.display_name, u.password_hash
            FROM users u
            WHERE lower(u.email) = $1 AND u.is_active = true
            """,
            normalized_email,
        )

    if row is None or not verify_password(password, row["password_hash"]):
        return None

    return AuthenticatedUser(
        user_id=int(row["user_id"]),
        email=str(row["email"]),
        display_name=str(row["display_name"]),
    )


async def organization_identities_for_user(user_id: int) -> list[Identity]:
    async with db_connection() as db:
        rows = await db.fetch(
            """
            SELECT u.id AS user_id, u.email, u.display_name,
                   o.id AS organization_id, o.name AS organization_name,
                   o.slug AS organization_slug, o.kind AS organization_kind,
                   m.role
            FROM users u
            JOIN organization_memberships m ON m.user_id = u.id
            JOIN organizations o ON o.id = m.organization_id
            WHERE u.id = $1 AND u.is_active = true
            ORDER BY (o.personal_owner_user_id = u.id) DESC, lower(o.name), o.id
            """,
            user_id,
        )

    return [_identity_from_row(row) for row in rows]


async def identity_for_user_organization(
    user_id: int,
    organization_id: int,
) -> Identity | None:
    async with db_connection() as db:
        row = await db.fetchrow(
            """
            SELECT u.id AS user_id, u.email, u.display_name,
                   o.id AS organization_id, o.name AS organization_name,
                   o.slug AS organization_slug, o.kind AS organization_kind,
                   m.role
            FROM users u
            JOIN organization_memberships m ON m.user_id = u.id
            JOIN organizations o ON o.id = m.organization_id
            WHERE u.id = $1 AND u.is_active = true AND o.id = $2
            """,
            user_id,
            organization_id,
        )

    return _identity_from_row(row) if row is not None else None


async def switch_session_organization(
    token_hash: str,
    user_id: int,
    organization_id: int,
) -> Identity:
    identity = await identity_for_user_organization(user_id, organization_id)

    if identity is None:
        raise HTTPException(404, "Workspace not found")

    async with db_connection() as db:
        result = await db.execute(
            """
            UPDATE user_sessions
            SET organization_id = $1, last_seen_at = now()
            WHERE token_hash = $2 AND user_id = $3 AND expires_at > now()
            """,
            organization_id,
            token_hash,
            user_id,
        )

    if result != "UPDATE 1":
        raise HTTPException(401, "Session expired")

    return identity


def normalize_organization_name(value: str) -> str:
    name = " ".join(value.strip().split())

    if not 1 <= len(name) <= 120:
        raise HTTPException(
            422,
            "Workspace name must be between 1 and 120 characters",
        )

    return name


def require_organization_write_access() -> Identity:
    identity = current_identity()

    if identity.role not in {"owner", "admin"}:
        raise HTTPException(403, "Owner or admin access is required")
    if (
        identity.oauth_scopes is not None
        and "settra:write" not in identity.oauth_scopes
    ):
        raise HTTPException(403, "The authorization does not grant write access")

    return identity


async def create_session(identity: Identity) -> tuple[str, str, datetime]:
    token = secrets.token_urlsafe(48)
    csrf_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=session_ttl_seconds())

    async with db_connection() as db, db.transaction():
        await db.execute(
            """
            INSERT INTO user_sessions (
                token_hash, user_id, organization_id, csrf_token_hash, expires_at
            ) VALUES ($1, $2, $3, $4, $5)
            """,
            hash_token(token),
            identity.user_id,
            identity.organization_id,
            hash_token(csrf_token),
            expires_at,
        )
        await db.execute("DELETE FROM user_sessions WHERE expires_at <= now()")

    return token, csrf_token, expires_at


async def load_session(token: str) -> SessionIdentity | None:
    if not token:
        return None

    token_hash = hash_token(token)
    async with db_connection() as db:
        row = await db.fetchrow(
            """
            SELECT s.token_hash, s.csrf_token_hash, s.expires_at,
                   u.id AS user_id, u.email, u.display_name,
                   o.id AS organization_id, o.name AS organization_name,
                   o.slug AS organization_slug, o.kind AS organization_kind,
                   m.role
            FROM user_sessions s
            JOIN users u ON u.id = s.user_id AND u.is_active = true
            JOIN organizations o ON o.id = s.organization_id
            JOIN organization_memberships m
              ON m.organization_id = s.organization_id AND m.user_id = s.user_id
            WHERE s.token_hash = $1 AND s.expires_at > now()
            """,
            token_hash,
        )
        if row is not None:
            await db.execute(
                "UPDATE user_sessions SET last_seen_at = now() WHERE token_hash = $1",
                token_hash,
            )

    if row is None:
        return None

    return SessionIdentity(
        identity=_identity_from_row(row),
        token_hash=row["token_hash"],
        csrf_token_hash=row["csrf_token_hash"],
        expires_at=row["expires_at"],
    )


async def delete_session(token: str) -> None:
    if not token:
        return

    async with db_connection() as db:
        await db.execute(
            "DELETE FROM user_sessions WHERE token_hash = $1",
            hash_token(token),
        )


def valid_csrf(session: SessionIdentity, cookie_token: str, header_token: str) -> bool:
    return (
        bool(cookie_token and header_token)
        and hmac.compare_digest(
            cookie_token,
            header_token,
        )
        and hmac.compare_digest(session.csrf_token_hash, hash_token(header_token))
    )


def identity_payload(identity: Identity) -> dict[str, Any]:
    return {
        "user": {
            "id": identity.user_id,
            "email": identity.email,
            "display_name": identity.display_name,
        },
        "organization": {
            "id": identity.organization_id,
            "name": identity.organization_name,
            "slug": identity.organization_slug,
            "kind": identity.organization_kind,
            "role": identity.role,
        },
    }


def hash_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def session_ttl_seconds() -> int:
    return max(3600, int(os.getenv("APP_SESSION_TTL_SECONDS", str(30 * 86400))))


def registration_enabled() -> bool:
    return os.getenv("REGISTRATION_ENABLED", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def secure_cookies() -> bool:
    configured = os.getenv("APP_SESSION_COOKIE_SECURE")
    if configured is not None and configured.strip():
        return configured.strip().lower() in {"1", "true", "yes", "on"}

    return os.getenv("PUBLIC_URL", "").strip().lower().startswith("https://")


def _identity_from_row(row: Any) -> Identity:
    return Identity(
        user_id=int(row["user_id"]),
        organization_id=int(row["organization_id"]),
        email=str(row["email"]),
        display_name=str(row["display_name"]),
        organization_name=str(row["organization_name"]),
        organization_slug=str(row["organization_slug"]),
        organization_kind=str(row["organization_kind"]),
        role=str(row["role"]),
    )


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _base64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
