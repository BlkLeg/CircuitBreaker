from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class DocBase(BaseModel):
    title: str
    body_md: str


class DocCreate(DocBase):
    pass


class DocUpdate(BaseModel):
    title: Optional[str] = None
    body_md: Optional[str] = None


class Doc(DocBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class EntityDocAttach(BaseModel):
    doc_id: int
    entity_type: str
    entity_id: int
