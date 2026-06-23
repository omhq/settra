from pydantic import BaseModel


class ConnectionCreate(BaseModel):
    name: str
    plugin: str
    credentials: dict[str, str]


class ConnectionUpdate(BaseModel):
    name: str
    credentials: dict[str, str]


class QueryRequest(BaseModel):
    sql: str
