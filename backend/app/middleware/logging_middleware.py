"""HTTP middleware that automatically logs all mutating API operations to the audit log."""
import json
import re
import logging
from datetime import datetime

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.db.session import SessionLocal

_logger = logging.getLogger(__name__)

# Paths that should never be logged (read-only or internal)
_SKIP_PATHS = re.compile(
    r"/(logs|health|openapi\.json|swagger|redoc|user-icons|icons|assets)",
    re.IGNORECASE,
)

# Map (method, path_pattern) → (action_template, category)
# Patterns are matched in order; first match wins.
# {entity} in action_template is replaced with the parsed entity type.
_ROUTE_RULES: list[tuple[str, re.Pattern, str, str]] = [
    ("POST",   re.compile(r"^/api/v1/bootstrap/initialize$"),             "bootstrap_create_user",      "bootstrap"),
    # Relationship endpoints (must come before simple CRUD patterns)
    ("POST",   re.compile(r"^/api/v1/services/\d+/dependencies$"),        "add_service_dependency",   "relationships"),
    ("DELETE", re.compile(r"^/api/v1/services/\d+/dependencies/\d+$"),    "remove_service_dependency","relationships"),
    ("POST",   re.compile(r"^/api/v1/services/\d+/storage$"),             "attach_service_storage",   "relationships"),
    ("DELETE", re.compile(r"^/api/v1/services/\d+/storage/\d+$"),         "detach_service_storage",   "relationships"),
    ("POST",   re.compile(r"^/api/v1/services/\d+/misc$"),                "attach_service_misc",      "relationships"),
    ("DELETE", re.compile(r"^/api/v1/services/\d+/misc/\d+$"),            "detach_service_misc",      "relationships"),
    ("POST",   re.compile(r"^/api/v1/networks/\d+/members$"),             "add_network_member",       "relationships"),
    ("DELETE", re.compile(r"^/api/v1/networks/\d+/members/\d+$"),         "remove_network_member",    "relationships"),
    ("POST",   re.compile(r"^/api/v1/docs/attach$"),                      "attach_doc",               "docs"),
    ("DELETE", re.compile(r"^/api/v1/docs/attach$"),                      "detach_doc",               "docs"),
    # Settings
    ("PUT",    re.compile(r"^/api/v1/settings$"),                         "update_settings",          "settings"),
    ("POST",   re.compile(r"^/api/v1/settings/reset$"),                   "reset_settings",           "settings"),
    # Simple CRUD — derive action from method + entity segment
    ("POST",   re.compile(r"^/api/v1/(?P<entity>[^/]+)$"),               "create_{entity}",           "crud"),
    ("PATCH",  re.compile(r"^/api/v1/(?P<entity>[^/]+)/\d+$"),           "update_{entity}",           "crud"),
    ("PUT",    re.compile(r"^/api/v1/(?P<entity>[^/]+)/\d+$"),           "update_{entity}",           "crud"),
    ("DELETE", re.compile(r"^/api/v1/(?P<entity>[^/]+)/\d+$"),           "delete_{entity}",           "crud"),
]

# Normalise entity segment → canonical entity_type string
_ENTITY_ALIASES = {
    "compute-units": "compute",
    "hardware":      "hardware",
    "services":      "service",
    "storage":       "storage",
    "networks":      "network",
    "misc":          "misc",
    "docs":          "doc",
    "settings":      "settings",
    "graphs":        "graph",
    "categories":    "category",
    "environments":  "environment",
}


def _entity_type_from_path(path: str) -> tuple[str | None, int | None]:
    """Extract entity_type and entity_id from a path like /api/v1/hardware/5."""
    m = re.match(r"^/api/v1/(?P<seg>[^/]+)(?:/(?P<eid>\d+))?", path)
    if not m:
        return None, None
    seg = m.group("seg")
    eid = int(m.group("eid")) if m.group("eid") else None
    entity_type = _ENTITY_ALIASES.get(seg, seg)
    return entity_type, eid


def _match_rule(method: str, path: str):
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
    return None, None


async def _read_body(request: Request) -> bytes:
    """Read and cache the request body so downstream handlers can still read it."""
    body = await request.body()
    # Re-inject so downstream can read it again
    async def receive():
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
    async def body_iterator():
        yield body

    response.body_iterator = body_iterator()  # type: ignore[attr-defined]
    return body


def _resolve_actor(request: Request) -> tuple[str, str | None]:
    """Extract the user's display name and gravatar hash from the JWT, or return ('anonymous', None)."""
    try:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return "anonymous", None
        token = auth_header[len("Bearer "):]

        from app.services.settings_service import get_or_create_settings
        from app.core.security import decode_token
        from app.db.models import User
        from sqlalchemy import select

        with SessionLocal() as db:
            cfg = get_or_create_settings(db)
            if not cfg.auth_enabled or not cfg.jwt_secret:
                return "anonymous", None
            user_id = decode_token(token, cfg.jwt_secret)
            if not user_id:
                return "anonymous", None
            user = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
            if user:
                return (user.display_name or user.email), user.gravatar_hash
            return "anonymous", None
    except Exception:
        return "anonymous", None


class LoggingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
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

        # Resolve the actor from JWT if present
        actor, actor_gravatar_hash = _resolve_actor(request)

        # Read request body (re-inject for downstream)
        req_body_bytes = await _read_body(request)
        req_body_str: str | None = None
        if req_body_bytes:
            try:
                req_body_str = req_body_bytes.decode("utf-8")
            except Exception:
                req_body_str = None

        # Fetch old value for updates/deletes
        old_value_str: str | None = None
        if method in {"PATCH", "PUT", "DELETE"} and entity_id and entity_type:
            try:
                old_value_str = _fetch_entity_json(entity_type, entity_id)
            except Exception:
                pass

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
                pass

        # For POST where new_value wasn't captured from response, fall back to request body
        if method == "POST" and not new_value_str and req_body_str:
            new_value_str = req_body_str

        # Extract entity_id from response body on POST (creation)
        if method == "POST" and new_value_str and entity_id is None:
            try:
                parsed = json.loads(new_value_str)
                entity_id = parsed.get("id")
            except Exception:
                pass

        # Extract entity_name from response JSON (best-effort)
        entity_name = ""
        if new_value_str:
            try:
                _parsed = json.loads(new_value_str)
                entity_name = _parsed.get("name") or _parsed.get("title") or ""
            except Exception:
                pass
        # Fall back to request body name if response had none
        if not entity_name and req_body_str:
            try:
                _parsed = json.loads(req_body_str)
                entity_name = _parsed.get("name") or _parsed.get("title") or ""
            except Exception:
                pass

        # Build structured diff from old/new values
        diff: dict | None = None
        try:
            before = json.loads(old_value_str) if old_value_str else None
            after  = json.loads(new_value_str) if new_value_str else None
            if before is not None or after is not None:
                diff = {"before": before, "after": after}
        except Exception:
            pass

        # Write log entry via the centralised service (always — including errors)
        try:
            _write_log(
                action=action,
                category=category,
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
                actor_gravatar_hash=actor_gravatar_hash,
            )
        except Exception as exc:
            _logger.warning("Audit log write failed: %s", exc)

        return response


def _fetch_entity_json(entity_type: str, entity_id: int) -> str | None:
    """Fetch the current entity state as a JSON string for old_value capture."""
    from sqlalchemy import select
    from app.db.models import (
        Hardware, ComputeUnit, Service, Storage, Network, MiscItem,
    )

    _MODEL_MAP = {
        "hardware": Hardware,
        "compute":  ComputeUnit,
        "service":  Service,
        "storage":  Storage,
        "network":  Network,
        "misc":     MiscItem,
    }
    model = _MODEL_MAP.get(entity_type)
    if not model:
        return None

    with SessionLocal() as db:
        row = db.execute(select(model).where(model.id == entity_id)).scalar_one_or_none()
        if row is None:
            return None
        # Serialize column attributes to a dict
        from sqlalchemy import inspect as sa_inspect
        data = {
            col.key: getattr(row, col.key)
            for col in sa_inspect(type(row)).column_attrs
        }
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
    actor_gravatar_hash: str | None = None,
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
    )
