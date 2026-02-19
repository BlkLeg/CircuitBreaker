from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class MiscItemBase(BaseModel):
    name: str
    kind: Optional[str] = None
    url: Optional[str] = None
    description: Optional[str] = None
    tags: list[str] = []


class MiscItemCreate(MiscItemBase):
    pass


class MiscItemUpdate(BaseModel):
    name: Optional[str] = None
    kind: Optional[str] = None
    url: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[list[str]] = None


class MiscItem(MiscItemBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
