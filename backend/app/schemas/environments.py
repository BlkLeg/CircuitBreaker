from typing import Optional
from pydantic import BaseModel, ConfigDict


class EnvironmentCreate(BaseModel):
    name: str
    color: Optional[str] = None


class EnvironmentUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None


class EnvironmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    color: Optional[str]
    created_at: str
    usage_count: int
