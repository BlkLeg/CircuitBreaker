"""Domain-level exception classes for Circuit Breaker.

Raise these from service functions; the global handler in main.py converts
them to the appropriate HTTP response automatically.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

_SAFE_FIELD_NAME = re.compile(r"^[a-zA-Z0-9_.-]{1,64}$")
_CONFLICT_ITEM_KEYS = frozenset(
    {"entity_type", "entity_id", "conflicting_ip", "conflicting_port", "protocol"}
)


def _safe_fields(fields: Mapping[str, str] | None) -> dict[str, str] | None:
    if not fields:
        return None
    return {
        key: value[:300]
        for key, value in fields.items()
        if _SAFE_FIELD_NAME.fullmatch(key) and isinstance(value, str)
    } or None


def _safe_context(error_code: str, context: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Project only context fields explicitly approved for a public error code."""
    if error_code != "ip_conflict" or not context:
        return None
    raw_conflicts = context.get("conflicts")
    if not isinstance(raw_conflicts, Sequence) or isinstance(raw_conflicts, (str, bytes)):
        return None
    conflicts: list[dict[str, Any]] = []
    for raw_item in raw_conflicts[:100]:
        if not isinstance(raw_item, Mapping):
            continue
        conflicts.append({key: raw_item[key] for key in _CONFLICT_ITEM_KEYS if key in raw_item})
    return {"conflicts": conflicts}


class AppError(Exception):
    """Base class for all application-level errors.

    Attributes:
        message:     Human-readable description surfaced to the client.
        status_code: HTTP status code to use when converting to a response.
        error_code:  Machine-readable error identifier (snake_case).
    """

    def __init__(
        self,
        message: str,
        status_code: int = 400,
        error_code: str = "app_error",
        *,
        fields: Mapping[str, str] | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        self.fields = _safe_fields(fields)
        self.context = _safe_context(error_code, context)


class NotFoundError(AppError):
    """Raised when a requested resource does not exist (→ 404)."""

    def __init__(self, message: str = "Resource not found.") -> None:
        super().__init__(message, status_code=404, error_code="not_found")


class ConflictError(AppError):
    """Raised when an operation would violate a uniqueness or foreign-key
    constraint (→ 409)."""

    def __init__(
        self,
        message: str = "A conflict occurred.",
        *,
        error_code: str = "conflict",
        fields: Mapping[str, str] | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message,
            status_code=409,
            error_code=error_code,
            fields=fields,
            context=context,
        )


class ValidationError(AppError):
    """Raised for domain-level validation failures that are caught before
    Pydantic gets a chance to raise a 422 (→ 400)."""

    def __init__(self, message: str = "Validation failed.") -> None:
        super().__init__(message, status_code=400, error_code="validation_error")
