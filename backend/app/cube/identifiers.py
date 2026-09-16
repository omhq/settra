import hashlib
import re
from collections.abc import Iterable

from app.errors import InvalidOperationError

POSTGRES_IDENTIFIER_MAX_LENGTH = 63
CUBE_MEMBER_ALIAS_SEPARATOR_LENGTH = 2
IDENTIFIER_HASH_LENGTH = 10


def cube_sql_alias(cube_name: str, member_names: Iterable[str]) -> str | None:
    """Budget PostgreSQL bytes after Cube's SQL alias name normalization."""
    # Cube's inflection.underscore inserts "_" before every ASCII capital.
    # Only the start of the full model.member path loses a leading underscore.
    normalized_cube = _underscore(cube_name).removeprefix("_")
    longest_member = max(
        (len(_underscore(name).encode("utf-8")) for name in member_names), default=0
    )
    max_alias_length = (
        POSTGRES_IDENTIFIER_MAX_LENGTH
        - CUBE_MEMBER_ALIAS_SEPARATOR_LENGTH
        - longest_member
    )

    if len(normalized_cube.encode("utf-8")) <= max_alias_length:
        return None
    if max_alias_length < IDENTIFIER_HASH_LENGTH + 2:
        raise InvalidOperationError(
            "Shorten Cube member names to leave room for a stable PostgreSQL SQL alias"
        )

    prefix_length = max_alias_length - IDENTIFIER_HASH_LENGTH - 1
    prefix = (
        normalized_cube.encode("utf-8")[:prefix_length]
        .decode("utf-8", errors="ignore")
        .rstrip("_")
    )

    return f"{prefix}_{_identifier_digest(cube_name)}"


def short_identifier(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value

    prefix_length = max_length - IDENTIFIER_HASH_LENGTH - 1
    prefix = value[:prefix_length].rstrip("_")

    return f"{prefix}_{_identifier_digest(value)}"


def _identifier_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:IDENTIFIER_HASH_LENGTH]


def _underscore(value: str) -> str:
    return re.sub(r"[A-Z]", lambda match: "_" + match.group(), value).lower()
