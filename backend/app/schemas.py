from typing import Any

from pydantic import BaseModel


class ConnectionCreate(BaseModel):
    name: str
    plugin: str
    credentials: dict[str, str]


class ConnectionUpdate(BaseModel):
    name: str
    credentials: dict[str, str]


class ModelConfigCreate(BaseModel):
    name: str
    provider: str
    config: dict[str, Any]


class ModelConfigUpdate(BaseModel):
    name: str
    config: dict[str, Any]


class QueryRequest(BaseModel):
    sql: str
