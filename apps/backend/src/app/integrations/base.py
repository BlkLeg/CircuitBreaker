"""Base classes for the CircuitBreaker integration plugin system."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class ConfigField:
    name: str
    label: str
    type: str  # "text" | "password" | "url" | "number"
    required: bool = True
    secret: bool = False
    placeholder: str = ""


@dataclass
class MonitorStatus:
    external_id: str
    name: str
    status: str  # "up" | "down" | "pending" | "maintenance"
    url: str | None = None
    uptime_7d: float | None = None
    uptime_30d: float | None = None


class IntegrationPlugin(ABC):
    """Abstract base for all integration plugins.

    Subclasses must define TYPE, DISPLAY_NAME, CONFIG_FIELDS as class attributes
    and implement test_connection() and sync().
    """

    TYPE: str
    DISPLAY_NAME: str
    CONFIG_FIELDS: list[ConfigField]

    @abstractmethod
    def test_connection(self, config: dict[str, Any]) -> tuple[bool, str]:
        """Test whether the integration credentials are valid.

        Returns (ok, message). Must never raise — catch all exceptions internally.
        """

    @abstractmethod
    def sync(self, config: dict[str, Any]) -> list[MonitorStatus]:
        """Pull the current status of all monitors from the external service.

        Returns a list of MonitorStatus objects. Must never raise — return [] on error.
        """
