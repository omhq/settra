from typing import Any

from pydantic import BaseModel


class ChatRequest(BaseModel):
    connection_id: int | None = None
    connection_ids: list[int] | None = None
    model_config_id: int | None = None
    message: str | None = None
    question: str | None = None
    thread_id: int | None = None
    request_id: str | None = None


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


class MessagingConfigCreate(BaseModel):
    name: str
    provider: str
    config: dict[str, Any]
    model_config_id: int
    connection_ids: list[int]


class MessagingConfigUpdate(BaseModel):
    name: str
    config: dict[str, Any]
    model_config_id: int
    connection_ids: list[int]


class QueryRequest(BaseModel):
    sql: str
