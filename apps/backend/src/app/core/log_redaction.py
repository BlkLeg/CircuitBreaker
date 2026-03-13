"""Centralized log message redaction for sensitive data."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable

_REDACTED = "[REDACTED]"

_SENSITIVE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(Bearer\s+)[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE), rf"\1{_REDACTED}"),
    (
        re.compile(
            r"((?:password|passwd|secret|token|api[_-]?key)\s*[:=]\s*)[^\s,;]+", re.IGNORECASE
        ),
        rf"\1{_REDACTED}",
    ),
    (
        re.compile(
            r"((?:password|passwd|secret|token|api[_-]?key)[\"']?\s*:\s*[\"'])[^\"']+([\"'])",
            re.IGNORECASE,
        ),
        rf"\1{_REDACTED}\2",
    ),
    (re.compile(r"(https?://)([^/\s:@]+):([^@\s/]+)@", re.IGNORECASE), rf"\1\2:{_REDACTED}@"),
)

_INSTALL_MARKER = "_cb_log_redaction_installed"


def sanitize_log_text(value: str) -> str:
    """Redact sensitive token/credential fragments from free-form log text."""
    sanitized = value
    for pattern, replacement in _SENSITIVE_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


class LogRedactionFilter(logging.Filter):
    """Filter that rewrites log records in-place to remove sensitive values."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            rendered = record.getMessage()
            record.msg = sanitize_log_text(rendered)
            record.args = ()
            return True
        if record.args and isinstance(record.args, tuple):
            record.args = tuple(
                sanitize_log_text(item) if isinstance(item, str) else item for item in record.args
            )
        return True


def install_global_log_redaction(logger_names: Iterable[str] | None = None) -> None:
    """Install redaction filter on root and selected named loggers exactly once."""
    filter_instance = LogRedactionFilter()
    root = logging.getLogger()
    if not getattr(root, _INSTALL_MARKER, False):
        root.addFilter(filter_instance)
        setattr(root, _INSTALL_MARKER, True)

    target_names = tuple(logger_names or ("uvicorn", "uvicorn.error", "uvicorn.access", "app"))
    for logger_name in target_names:
        logger = logging.getLogger(logger_name)
        if getattr(logger, _INSTALL_MARKER, False):
            continue
        logger.addFilter(filter_instance)
        setattr(logger, _INSTALL_MARKER, True)
