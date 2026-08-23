from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ConnectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    credentials: dict[str, str]


class ConnectionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    credentials: dict[str, str]


class SyncConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str


class CollectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    agent_instructions: str = ""
    pipe_ids: list[int] = Field(default_factory=list)


class CollectionUpdate(CollectionCreate):
    pass


class QueryRequest(BaseModel):
    query: dict[str, Any] | list[dict[str, Any]]
