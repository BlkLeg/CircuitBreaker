"""HTTP middleware that automatically logs all mutating API operations to the audit log."""

import asyncio
import json
import logging
import re
from collections.abc import AsyncGenerator, Awaitable, Callable
from datetime import datetime

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.db.session import SessionLocal

_logger = logging.getLogger(__name__)

# Paths that should never be logged (read-only, internal, or contain credentials)
# Auth paths must never have request/response bodies captured — they contain passwords.
_SKIP_PATHS = re.compile(
    r"/(logs|health|openapi\.json|swagger|redoc|user-icons|icons|assets|bootstrap|auth)",
    re.IGNORECASE,
)

# Map (method, path_pattern) → (action_template, category)
# Patterns are matched in order; first match wins.
# {entity} in action_template is replaced with the parsed entity type.
_ROUTE_RULES: list[tuple[str, re.Pattern, str, str]] = [
    ("POST", re.compile(r"^/api/v1/bootstrap/initialize$"), "bootstrap_create_user", "bootstrap"),
    # Relationship endpoints (must come before simple CRUD patterns)
    (
        "POST",
        re.compile(r"^/api/v1/services/\d+/dependencies$"),
        "add_service_dependency",
        "relationships",
    ),
    (
        "DELETE",
        re.compile(r"^/api/v1/services/\d+/dependencies/\d+$"),
        "remove_service_dependency",
        "relationships",
    ),
    (
        "POST",
        re.compile(r"^/api/v1/services/\d+/storage$"),
        "attach_service_storage",
        "relationships",
    ),
    (
        "DELETE",
        re.compile(r"^/api/v1/services/\d+/storage/\d+$"),
        "detach_service_storage",
        "relationships",
    ),
    ("POST", re.compile(r"^/api/v1/services/\d+/misc$"), "attach_service_misc", "relationships"),
    (
        "DELETE",
        re.compile(r"^/api/v1/services/\d+/misc/\d+$"),
        "detach_service_misc",
        "relationships",
    ),
    ("POST", re.compile(r"^/api/v1/networks/\d+/members$"), "add_network_member", "relationships"),
    (
        "DELETE",
        re.compile(r"^/api/v1/networks/\d+/members/\d+$"),
        "remove_network_member",
        "relationships",
    ),
    ("POST", re.compile(r"^/api/v1/docs/attach$"), "attach_doc", "docs"),
    ("DELETE", re.compile(r"^/api/v1/docs/attach$"), "detach_doc", "docs"),
    # Graph / topology map actions
    ("POST", re.compile(r"^/api/v1/graph/layout$"), "save_graph_layout", "graph"),
    ("POST", re.compile(r"^/api/v1/graph/place-node$"), "place_graph_node", "graph"),
    ("PATCH", re.compile(r"^/api/v1/graph/edges/.+$"), "update_graph_edge", "graph"),
    ("DELETE", re.compile(r"^/api/v1/graph/edges/.+$"), "delete_graph_edge", "graph"),
    # Settings
    ("PUT", re.compile(r"^/api/v1/settings$"), "update_settings", "settings"),
    ("POST", re.compile(r"^/api/v1/settings/reset$"), "reset_settings", "settings"),
    # Simple CRUD — derive action from method + entity segment
    ("POST", re.compile(r"^/api/v1/(?P<entity>[^/]+)$"), "create_{entity}", "crud"),
    ("PATCH", re.compile(r"^/api/v1/(?P<entity>[^/]+)/\d+$"), "update_{entity}", "crud"),
    ("PUT", re.compile(r"^/api/v1/(?P<entity>[^/]+)/\d+$"), "update_{entity}", "crud"),
    ("DELETE", re.compile(r"^/api/v1/(?P<entity>[^/]+)/\d+$"), "delete_{entity}", "crud"),
]

# Normalise entity segment → canonical entity_type string
_ENTITY_ALIASES = {
    "compute-units": "compute",
    "hardware": "hardware",
    "hardware-connections": "hardware_connection",
    "hardware-clusters": "cluster",
    "services": "service",
    "service-external-nodes": "service_external_dependency",
    "storage": "storage",
    "networks": "network",
    "external-node-networks": "external_network_link",
    "external-nodes": "external_node",
    "misc": "misc",
    "docs": "doc",
    "settings": "settings",
    "graphs": "graph",
    "categories": "category",
    "environments": "environment",
}


def _singularize(value: str) -> str:
    """Best-effort singularization for action labels."""
    if value.endswith("ies") and len(value) > 3:
        return value[:-3] + "y"
    if value.endswith("s") and len(value) > 1:
        return value[:-1]
    return value


def _normalize_segment(segment: str) -> str:
    """Normalize a path segment to canonical snake-case style for action names."""
    aliased = _ENTITY_ALIASES.get(segment, segment)
    return aliased.replace("-", "_")


def _derive_nested_relationship_action(method: str, path: str) -> tuple[str | None, str | None]:
    """Fallback action derivation for nested routes like /api/v1/networks/1/hardware-members."""
    m = re.match(r"^/api/v1/(?P<entity>[^/]+)/\d+/(?P<child>[^/]+)(?:/[^/]+)?$", path)
    if not m:
        return None, None

    child = _normalize_segment(m.group("child"))
    child = _singularize(child)

    if method == "POST":
        return f"add_{child}", "relationships"
    if method == "DELETE":
        return f"remove_{child}", "relationships"
    if method in {"PATCH", "PUT"}:
        return f"update_{child}", "relationships"

    return None, None


def _entity_type_from_path(path: str) -> tuple[str | None, int | None]:
    """Extract entity_type and entity_id from a path like /api/v1/hardware/5."""
    m = re.match(r"^/api/v1/(?P<seg>[^/]+)(?:/(?P<eid>\d+))?", path)
    if not m:
        return None, None
    seg = m.group("seg")
    eid = int(m.group("eid")) if m.group("eid") else None
    entity_type = _ENTITY_ALIASES.get(seg, seg)
    return entity_type, eid


def _match_rule(method: str, path: str) -> tuple[str | None, str | None]:
    """Return (action, category) for the request, or (None, None) if not matched."""
    for rule_method, pattern, action_tpl, category in _ROUTE_RULES:
        if rule_method != method:
            continue
        m = pattern.match(path)
        if m:
            try:
                seg = m.group("entity")
                entity_norm = _ENTITY_ALIASES.get(seg, seg).rstrip("s")  # plural → singular
                action = action_tpl.replace("{entity}", entity_norm)
            except IndexError:
                action = action_tpl
            return action, category

    fallback_action, fallback_category = _derive_nested_relationship_action(method, path)
    if fallback_action:
        return fallback_action, fallback_category

    return None, None


async def _read_body(request: Request) -> bytes:
    """Read and cache the request body so downstream handlers can still read it."""
    body = await request.body()

    # Re-inject so downstream can read it again
    async def receive() -> dict:
        return {"type": "http.request", "body": body, "more_body": False}

    request._receive = receive  # noqa: SLF001
    return body


async def _read_response_body(response: Response) -> bytes:
    """Collect bytes from a streaming response."""
    chunks = []
    async for chunk in response.body_iterator:  # type: ignore[attr-defined]
        if isinstance(chunk, str):
            chunk = chunk.encode()
        chunks.append(chunk)
    body = b"".join(chunks)

    # Re-inject the body so the client still receives it
    async def body_iterator() -> AsyncGenerator[bytes, None]:
        yield body

    response.body_iterator = body_iterator()  # type: ignore[attr-defined]
    return body


def _resolve_actor(request: Request) -> tuple[str, str | None, int | None, str | None]:
    """Extract the user's display name, gravatar hash, ID, and role from the request.

    Resolution order:
      1. CB_API_TOKEN (legacy middleware flag or raw Bearer match)
      2. FastAPI-Users JWT (``sub`` claim with ``aud=["fastapi-users:auth"]``)
      3. Legacy JWT (``user_id`` claim, no audience)

    Returns ('anonymous', None, None, None) when no valid credential is present.
    """
    import os

    import jwt as pyjwt
    from sqlalchemy import select

    from app.core.security import _extract_token
    from app.db.models import User

    try:
        # 1. API or Session Token (Bearer header or cb_session cookie)
        if getattr(request.state, "legacy_admin", False):
            return "api-token", None, 0, "api-token"

        token = _extract_token(request)
        if not token:
            return "anonymous", None, None, None

        api_token = os.getenv("CB_API_TOKEN")
        if api_token and token == api_token:
            return "api-token", None, 0, "api-token"

        from app.services.settings_service import get_or_create_settings

        with SessionLocal() as db:
            cfg = get_or_create_settings(db)
            if not cfg.jwt_secret:
                return "anonymous", None, None, None

            user_id: int | None = None

            # 2. Session JWT (FastAPI-Users sub or CB user_id, both with audience)
            try:
                payload = pyjwt.decode(
                    token,
                    cfg.jwt_secret,
                    algorithms=["HS256"],
                    audience=["fastapi-users:auth"],
                )
                sub = payload.get("sub")
                if sub is not None:
                    user_id = int(sub)
                else:
                    uid = payload.get("user_id")
                    if uid is not None:
                        user_id = uid
            except (pyjwt.PyJWTError, ValueError, TypeError):
                pass

            if not user_id:
                return "anonymous", None, None, None

            user = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
            if user:
                return (user.display_name or user.email), user.gravatar_hash, user.id, user.role
            return "anonymous", None, None, None
    except Exception:
        _logger.debug("Failed to resolve actor from request", exc_info=True)
        return "anonymous", None, None, None


class LoggingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        method = request.method
        path = request.url.path

        # Only log mutating methods
        if method not in {"POST", "PATCH", "PUT", "DELETE"}:
            return await call_next(request)

        # Skip non-API and excluded paths
        if not path.startswith("/api/v1/") or _SKIP_PATHS.search(path):
            return await call_next(request)

        action, category = _match_rule(method, path)
        if not action:
            return await call_next(request)

        entity_type, entity_id = _entity_type_from_path(path)
        user_agent = request.headers.get("user-agent")
        ip_address = request.client.host if request.client else None

        # Resolve the actor from JWT if present — run in executor to avoid blocking event loop
        loop = asyncio.get_running_loop()
        actor, actor_gravatar_hash, actor_id, role_at_time = await loop.run_in_executor(
            None, _resolve_actor, request
        )

        # Read request body (re-inject for downstream)
        req_body_bytes = await _read_body(request)
        req_body_str: str | None = None
        if req_body_bytes:
            try:
                req_body_str = req_body_bytes.decode("utf-8")
            except Exception:
                _logger.debug("Failed to decode request body as UTF-8", exc_info=True)
                req_body_str = None

        # Fetch old value for updates/deletes — run in executor to avoid blocking event loop
        old_value_str: str | None = None
        if method in {"PATCH", "PUT", "DELETE"} and entity_id and entity_type:
            try:
                old_value_str = await loop.run_in_executor(
                    None, _fetch_entity_json, entity_type, entity_id
                )
            except Exception:
                _logger.debug("Failed to fetch old entity value for audit diff", exc_info=True)

        # Process request
        response = await call_next(request)
        status_code = response.status_code

        # Determine log level from HTTP status
        if status_code >= 500:
            level = "error"
        elif status_code >= 400:
            level = "warn"
        else:
            level = "info"

        # Collect response body for new_value on successful creates/updates
        new_value_str: str | None = None
        if level == "info":
            try:
                resp_body = await _read_response_body(response)
                if method in {"POST", "PATCH", "PUT"} and resp_body:
                    new_value_str = resp_body.decode("utf-8")
            except Exception:
                _logger.debug("Failed to read/decode response body for audit log", exc_info=True)

        # For POST where new_value wasn't captured from response, fall back to request body
        if method == "POST" and not new_value_str and req_body_str:
            new_value_str = req_body_str

        # Extract entity_id from response body on POST (creation)
        if method == "POST" and new_value_str and entity_id is None:
            try:
                parsed = json.loads(new_value_str)
                entity_id = parsed.get("id")
            except Exception:
                _logger.debug("Failed to parse entity_id from response JSON", exc_info=True)

        # Extract entity_name from response JSON (best-effort)
        entity_name = ""
        if new_value_str:
            try:
                _parsed = json.loads(new_value_str)
                entity_name = _parsed.get("name") or _parsed.get("title") or ""
            except Exception:
                _logger.debug("Failed to parse entity_name from response JSON", exc_info=True)
        # Fall back to request body name if response had none
        if not entity_name and req_body_str:
            try:
                _parsed = json.loads(req_body_str)
                entity_name = _parsed.get("name") or _parsed.get("title") or ""
            except Exception:
                _logger.debug("Failed to parse entity_name from request JSON", exc_info=True)

        # Build structured diff from old/new values
        diff: dict | None = None
        try:
            before = json.loads(old_value_str) if old_value_str else None
            after = json.loads(new_value_str) if new_value_str else None
            if before is not None or after is not None:
                diff = {"before": before, "after": after}
        except Exception:
            _logger.debug("Failed to build audit diff from old/new values", exc_info=True)

        # Write log entry — fire-and-forget in executor so the response is not delayed
        loop.run_in_executor(
            None,
            lambda: _write_log(
                action=action,
                category=category or "",
                level=level,
                status_code=status_code,
                entity_type=entity_type,
                entity_id=entity_id,
                entity_name=entity_name,
                diff=diff,
                old_value=old_value_str,
                new_value=new_value_str,
                user_agent=user_agent,
                ip_address=ip_address,
                details=req_body_str if category != "crud" else None,
                actor=actor,
                actor_id=actor_id,
                actor_gravatar_hash=actor_gravatar_hash,
                role_at_time=role_at_time,
            ),
        )

        return response


def _fetch_entity_json(entity_type: str, entity_id: int) -> str | None:
    """Fetch the current entity state as a JSON string for old_value capture."""
    from sqlalchemy import select

    from app.db.models import (
        ComputeUnit,
        Hardware,
        MiscItem,
        Network,
        Service,
        Storage,
    )

    _MODEL_MAP = {
        "hardware": Hardware,
        "compute": ComputeUnit,
        "service": Service,
        "storage": Storage,
        "network": Network,
        "misc": MiscItem,
    }
    model = _MODEL_MAP.get(entity_type)
    if not model:
        return None

    with SessionLocal() as db:
        row = db.execute(select(model).where(model.id == entity_id)).scalar_one_or_none()  # type: ignore[attr-defined]
        if row is None:
            return None
        # Serialize column attributes to a dict
        from sqlalchemy import inspect as sa_inspect

        data = {col.key: getattr(row, col.key) for col in sa_inspect(type(row)).column_attrs}
        # Convert datetimes to ISO strings
        for k, v in data.items():
            if isinstance(v, datetime):
                data[k] = v.isoformat()
        return json.dumps(data)


def _scrub_sensitive_data(json_str: str | None) -> str | None:
    """Parse JSON, scrub sensitive keys, and re-serialize (legacy compat shim)."""
    if not json_str:
        return json_str
    try:
        data = json.loads(json_str)
    except Exception:
        _logger.debug("Failed to parse JSON for sensitive data scrubbing", exc_info=True)
        return json_str
    from app.services.log_service import sanitise_diff

    return json.dumps(sanitise_diff(data))


def _write_log(
    *,
    action: str,
    category: str,
    level: str = "info",
    status_code: int | None = None,
    entity_type: str | None,
    entity_id: int | None,
    entity_name: str = "",
    diff: dict | None = None,
    old_value: str | None,
    new_value: str | None,
    user_agent: str | None,
    ip_address: str | None,
    details: str | None,
    actor: str = "anonymous",
    actor_id: int | None = None,
    actor_gravatar_hash: str | None = None,
    role_at_time: str | None = None,
) -> None:
    """Delegate to log_service.write_log — the single write path for the audit log."""
    # Scrub sensitive data from legacy JSON blobs
    scrubbed_old_value = _scrub_sensitive_data(old_value)
    scrubbed_new_value = _scrub_sensitive_data(new_value)
    scrubbed_details = _scrub_sensitive_data(details)

    from app.services.log_service import write_log

    write_log(
        db=None,  # log_service opens its own session
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_name=entity_name,
        diff=diff,
        actor_name=actor,
        actor_id=actor_id,
        ip_address=ip_address,
        severity=level,
        category=category,
        level=level,
        status_code=status_code,
        old_value=scrubbed_old_value,
        new_value=scrubbed_new_value,
        user_agent=user_agent,
        details=scrubbed_details,
        actor=actor,
        actor_gravatar_hash=actor_gravatar_hash,
        role_at_time=role_at_time,
    )
