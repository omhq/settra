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


class RowKeyDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    columns: list[str]
    format: str | None = None


class ConnectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    credentials: dict[str, str | list[str]]
    destination_id: int | None = None
    row_keys: dict[str, RowKeyDefinition | list[str]] | None = None


class ConnectionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    credentials: dict[str, str | list[str]]
    destination_id: int | None = None
    row_keys: dict[str, RowKeyDefinition | list[str]] | None = None


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


class AppGraphValidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str | None = None
    target_node_id: str | None = None


class AppGraphExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str | None = None
    target_node_id: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class AppGraphParameterOptionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str | None = None
    search: str | None = Field(default=None, max_length=100)


class CollectionGraphUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str
    layout: dict[str, Any] = Field(default_factory=dict)
    expected_revision: int = Field(ge=0)


class QueryRequest(BaseModel):
    query: dict[str, Any] | list[dict[str, Any]]
