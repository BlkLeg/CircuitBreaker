from pydantic import BaseModel, ConfigDict


class EnvironmentCreate(BaseModel):
    name: str
    color: str | None = None


class EnvironmentUpdate(BaseModel):
    name: str | None = None
    color: str | None = None


class EnvironmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    color: str | None
    created_at: str
    usage_count: int
