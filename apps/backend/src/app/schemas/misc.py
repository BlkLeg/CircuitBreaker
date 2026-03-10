from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MiscItemBase(BaseModel):
    name: str
    kind: str | None = None
    icon_slug: str | None = None
    url: str | None = None
    description: str | None = None
    tags: list[str] = []


class MiscItemCreate(MiscItemBase):
    pass


class MiscItemUpdate(BaseModel):
    name: str | None = None
    kind: str | None = None
    icon_slug: str | None = None
    url: str | None = None
    description: str | None = None
    tags: list[str] | None = None


class MiscItem(MiscItemBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
