from datetime import datetime
from typing import Any, Literal, Optional
from pydantic import BaseModel, ConfigDict, field_validator
import json
import logging

_logger = logging.getLogger(__name__)


class AppSettingsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    theme: str
    default_environment: Optional[str] = None
    show_experimental_features: bool
    api_base_url: Optional[str] = None
    map_default_filters: Optional[str] = None  # JSON string
    vendor_icon_mode: str
    environments: list[str] = ["prod", "staging", "dev"]
    categories: list[str] = []
    locations: list[str] = []
    dock_order: Optional[list[str]] = None
    created_at: datetime
    updated_at: datetime

    @field_validator('environments', mode='before')
    @classmethod
    def parse_environments(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception as exc:
                _logger.warning("Failed to parse 'environments' setting, using default. Error: %s", exc)
                return ["prod", "staging", "dev"]
        if v is None:
            return ["prod", "staging", "dev"]
        return v

    @field_validator('categories', mode='before')
    @classmethod
    def parse_categories(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception as exc:
                _logger.warning("Failed to parse 'categories' setting, using default. Error: %s", exc)
                return []
        if v is None:
            return []
        return v

    @field_validator('locations', mode='before')
    @classmethod
    def parse_locations(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception as exc:
                _logger.warning("Failed to parse 'locations' setting, using default. Error: %s", exc)
                return []
        if v is None:
            return []
        return v

    @field_validator('dock_order', mode='before')
    @classmethod
    def parse_dock_order(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception as exc:
                _logger.warning("Failed to parse 'dock_order' setting, using default. Error: %s", exc)
                return None
        return v


class AppSettingsUpdate(BaseModel):
    theme: Optional[Literal["auto", "dark", "light"]] = None
    default_environment: Optional[str] = None
    show_experimental_features: Optional[bool] = None
    api_base_url: Optional[str] = None
    map_default_filters: Optional[Any] = None  # accepts dict or None; serialized to JSON string
    vendor_icon_mode: Optional[Literal["none", "built_in", "custom_files"]] = None
    environments: Optional[list[str]] = None
    categories: Optional[list[str]] = None
    locations: Optional[list[str]] = None
    dock_order: Optional[list[str]] = None
