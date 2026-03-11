"""Standard error response schema for API consistency (PROMPT.md step 7)."""

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """Consistent error payload for 4xx/5xx responses."""

    error_code: str = Field(..., description="Machine-readable code for client handling")
    detail: str = Field(..., description="Human-readable message")
    fields: dict[str, str] | None = Field(default=None, description="Field-level validation errors")
    retry_after: int | None = Field(default=None, description="Seconds until retry (429 only)")


# Common error codes for documentation and client handling
class ErrorCodes:
    INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    RATE_LIMITED = "RATE_LIMITED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
