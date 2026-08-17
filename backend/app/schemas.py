from typing import Any

from pydantic import BaseModel, ConfigDict


class ConnectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    credentials: dict[str, str]


class ConnectionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    credentials: dict[str, str]


class QueryRequest(BaseModel):
    query: dict[str, Any] | list[dict[str, Any]]
