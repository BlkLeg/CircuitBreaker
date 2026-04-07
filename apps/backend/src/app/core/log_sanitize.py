"""Utilities for safe structured logging (log injection + accidental secret leakage)."""

from __future__ import annotations

import re
from typing import Any

# Strip control characters that can forge multi-line log records (CVE-class log injection).
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Redact common `key=value` / JSON-ish secret patterns in untrusted error strings.
_SECRET_KV_RE = re.compile(
    r"(?i)\b(api[_-]?key|api[_-]?secret|secret|token|password|authorization)\s*[:=]\s*[^\s&,\"']+"
)


def safe_log_fragment(value: Any, max_len: int = 200) -> str:
    """Return a single-line, length-limited string safe to embed in log messages."""
    s = str(value)
    s = _CTRL_RE.sub(" ", s)
    s = _SECRET_KV_RE.sub(lambda m: f"{m.group(1)}=<redacted>", s)
    s = " ".join(s.split())
    if len(s) > max_len:
        return f"{s[: max_len - 3]}..."
    return s
