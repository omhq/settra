from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AccountRegister(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str
    display_name: str
    password: str


class AccountLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str
    password: str


class ActiveOrganizationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: int


class OrganizationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str


class ConnectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    credentials: dict[str, str | list[str]]
    destination_id: int | None = None


class ConnectionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    credentials: dict[str, str | list[str]]
    destination_id: int | None = None


class GooglePickerFileInspection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_id: str


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
