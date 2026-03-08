from pydantic import BaseModel, ConfigDict


class CategoryCreate(BaseModel):
    name: str
    color: str | None = None


class CategoryUpdate(BaseModel):
    name: str | None = None
    color: str | None = None


class CategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    color: str | None
    created_at: str
    service_count: int
