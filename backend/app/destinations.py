from __future__ import annotations

import json

from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import quote

from app.common.config import (
    POSTGRES_DATABASE,
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
)

MANAGED_DESTINATION_SLUG = "built_in_postgres"


@dataclass(frozen=True)
class DestinationRuntime:
    id: int
    name: str
    slug: str
    type: str
    schema: str
    configuration: dict[str, Any]
    is_builtin: bool

    def postgres_dsn(self) -> str:
        self.require_built_in_postgres()
        return (
            f"postgresql://{quote(POSTGRES_USER, safe='')}:"
            f"{quote(POSTGRES_PASSWORD, safe='')}@{POSTGRES_HOST}:"
            f"{POSTGRES_PORT}/{quote(POSTGRES_DATABASE, safe='')}"
        )

    def postgres_connect_kwargs(self) -> dict[str, Any]:
        self.require_built_in_postgres()
        return {
            "host": POSTGRES_HOST,
            "port": POSTGRES_PORT,
            "dbname": POSTGRES_DATABASE,
            "user": POSTGRES_USER,
            "password": POSTGRES_PASSWORD,
        }

    def asyncpg_connect_kwargs(self) -> dict[str, Any]:
        values = self.postgres_connect_kwargs()
        values["database"] = values.pop("dbname")
        return values

    def require_built_in_postgres(self) -> None:
        if (
            self.type != "postgres"
            or not self.is_builtin
            or self.configuration.get("mode") != "environment"
        ):
            raise ValueError(
                f"Destination {self.name!r} is registered but is not supported by "
                "this Settra build"
            )


def runtime_from_connection(connection: Mapping[str, Any]) -> DestinationRuntime:
    return DestinationRuntime(
        id=int(connection.get("destination_id") or 0),
        name=str(connection.get("destination_name") or "managed PostgreSQL"),
        slug=str(connection.get("destination_slug") or MANAGED_DESTINATION_SLUG),
        type=str(connection.get("destination_type") or "postgres"),
        schema=str(connection.get("destination_schema") or connection["slug"]),
        configuration=(
            _configuration(connection.get("destination_configuration"))
            or {"mode": "environment"}
        ),
        is_builtin=bool(connection.get("destination_is_builtin", True)),
    )


def built_in_destination_runtime(schema: str) -> DestinationRuntime:
    return DestinationRuntime(
        id=0,
        name="Managed PostgreSQL",
        slug=MANAGED_DESTINATION_SLUG,
        type="postgres",
        schema=schema,
        configuration={"mode": "environment"},
        is_builtin=True,
    )


def public_destination(
    row: Mapping[str, Any],
    *,
    schema: str | None = None,
) -> dict[str, Any]:
    destination_type = str(row.get("type") or row.get("destination_type") or "")
    is_builtin = bool(
        row.get("is_builtin")
        if row.get("is_builtin") is not None
        else row.get("destination_is_builtin")
    )
    configuration = _configuration(
        row.get("configuration") or row.get("destination_configuration")
    )
    response = {
        "id": int(row.get("id") or row.get("destination_id") or 0),
        "name": str(row.get("name") or row.get("destination_name") or ""),
        "slug": str(row.get("slug") or row.get("destination_slug") or ""),
        "type": destination_type,
        "is_builtin": is_builtin,
        "is_default": bool(
            row.get("is_default")
            if row.get("is_default") is not None
            else row.get("destination_is_default")
        ),
        "configuration_mode": str(configuration.get("mode") or "unknown"),
        "configurable": not is_builtin,
    }

    if schema is not None:
        response["schema"] = schema

    if destination_type == "postgres" and is_builtin:
        response["location"] = {
            "host": POSTGRES_HOST,
            "port": POSTGRES_PORT,
            "database": POSTGRES_DATABASE,
        }

    return response


def connection_destination(row: Mapping[str, Any]) -> dict[str, Any]:
    return public_destination(
        {
            "id": row.get("destination_id") or 0,
            "name": row.get("destination_name") or "Managed PostgreSQL",
            "slug": row.get("destination_slug") or MANAGED_DESTINATION_SLUG,
            "type": row.get("destination_type") or "postgres",
            "configuration": (
                row.get("destination_configuration") or {"mode": "environment"}
            ),
            "is_builtin": row.get("destination_is_builtin", True),
            "is_default": row.get("destination_is_default", True),
        },
        schema=str(row.get("destination_schema") or row["slug"]),
    )


def _configuration(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}
