from typing import Optional
from pydantic import BaseModel, ConfigDict


class CategoryCreate(BaseModel):
    name: str
    color: Optional[str] = None


class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None


class CategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    color: Optional[str]
    created_at: str
    service_count: int
