"""Domain-level exception classes for Circuit Breaker.

Raise these from service functions; the global handler in main.py converts
them to the appropriate HTTP response automatically.
"""
from __future__ import annotations


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
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code


class NotFoundError(AppError):
    """Raised when a requested resource does not exist (→ 404)."""

    def __init__(self, message: str = "Resource not found.") -> None:
        super().__init__(message, status_code=404, error_code="not_found")


class ConflictError(AppError):
    """Raised when an operation would violate a uniqueness or foreign-key
    constraint (→ 409)."""

    def __init__(self, message: str = "A conflict occurred.") -> None:
        super().__init__(message, status_code=409, error_code="conflict")


class ValidationError(AppError):
    """Raised for domain-level validation failures that are caught before
    Pydantic gets a chance to raise a 422 (→ 400)."""

    def __init__(self, message: str = "Validation failed.") -> None:
        super().__init__(message, status_code=400, error_code="validation_error")
