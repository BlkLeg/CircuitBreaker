"""Central air-gap policy for application-initiated HTTP(S)."""

from __future__ import annotations

import ipaddress
import os
import threading
import time
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import httpx
    import requests


class HTTPPolicy(StrEnum):
    PUBLIC_HTTP = "public_http"
    PRIVATE_LAN_HTTP = "private_lan_http"


PUBLIC_HTTP = HTTPPolicy.PUBLIC_HTTP
PRIVATE_LAN_HTTP = HTTPPolicy.PRIVATE_LAN_HTTP
_lock = threading.Lock()
_until = 0.0
_value = False


def invalidate_airgap_cache() -> None:
    global _until
    with _lock:
        _until = 0.0


def airgap_enabled() -> bool:
    global _until, _value
    if os.getenv("CB_AIRGAP", "").strip().lower() in {"1", "true", "yes", "on"}:
        return True
    now = time.monotonic()
    with _lock:
        if now < _until:
            return _value
        enabled = False
        try:
            from app.db.models import AppSettings
            from app.db.session import SessionLocal

            db = SessionLocal()
            try:
                row = db.query(AppSettings.airgap_mode).filter(AppSettings.id == 1).first()
                enabled = bool(row and row[0])
            finally:
                db.close()
        except Exception:
            enabled = False
        _value, _until = enabled, now + 5.0
        return enabled


def enforce_before_resolution(policy: HTTPPolicy) -> None:
    if airgap_enabled() and policy is PUBLIC_HTTP:
        raise ConnectionError("Public HTTP is disabled while air-gap mode is enabled")


def enforce_resolved(policy: HTTPPolicy, addresses: tuple[str, ...]) -> None:
    if not airgap_enabled() or policy is PUBLIC_HTTP:
        return
    if not addresses:
        raise ConnectionError("Private-LAN HTTP target did not resolve in air-gap mode")
    for value in addresses:
        ip = ipaddress.ip_address(value)
        if not (ip.is_private or ip.is_loopback):
            raise ConnectionError("Private-LAN HTTP target has a public or mixed DNS answer")


def httpx_client(policy: HTTPPolicy = PUBLIC_HTTP, **kwargs: Any) -> httpx.Client:
    """Construct the only supported synchronous server-side HTTP client."""
    import httpx

    enforce_before_resolution(policy)
    return httpx.Client(**kwargs)


def httpx_async_client(policy: HTTPPolicy = PUBLIC_HTTP, **kwargs: Any) -> httpx.AsyncClient:
    """Construct the only supported asynchronous server-side HTTP client."""
    import httpx

    enforce_before_resolution(policy)
    return httpx.AsyncClient(**kwargs)


def httpx_request(
    method: str, url: str, *, policy: HTTPPolicy = PUBLIC_HTTP, **kwargs: Any
) -> httpx.Response:
    import httpx

    enforce_before_resolution(policy)
    return httpx.request(method, url, **kwargs)


def httpx_get(url: str, *, policy: HTTPPolicy = PUBLIC_HTTP, **kwargs: Any) -> httpx.Response:
    import httpx

    enforce_before_resolution(policy)
    return httpx.get(url, **kwargs)


def requests_session(policy: HTTPPolicy = PUBLIC_HTTP) -> requests.Session:
    import requests

    enforce_before_resolution(policy)
    return requests.Session()


def boto3_client(*, policy: HTTPPolicy = PUBLIC_HTTP, **kwargs: Any) -> Any:
    import boto3

    enforce_before_resolution(policy)
    return boto3.client(**kwargs)
