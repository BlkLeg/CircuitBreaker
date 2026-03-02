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
    category: Optional[str] = None
    pinned: Optional[bool] = None
    icon: Optional[str] = None


class Doc(DocBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    body_html: Optional[str] = None
    category: str = ""
    pinned: bool = False
    icon: str = ""
    created_at: datetime
    updated_at: datetime


class EntityDocAttach(BaseModel):
    doc_id: int
    entity_type: str
    entity_id: int


class DocEntityLink(BaseModel):
    """A single entity that a doc is linked to."""
    entity_type: str
    entity_id: int
