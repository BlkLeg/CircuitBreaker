"""Value-shape rules for the settings ``cb config validate`` resolves (SRV-05).

``app.core.startup_validation`` answers "is this combination of settings
allowed?".  It cannot answer "is this value even the right *kind* of thing?",
because by the time it runs the value has already been read: ``server.port =
"not-a-port"`` in config.toml becomes ``CB_PORT=not-a-port``, every gate passes,
and the report said *valid* about a configuration that cannot serve a request.

So this module answers the second question, and it answers it the way the
reader of each setting actually reads it rather than by a generic type table.
That distinction is the whole point:

* ``CB_ALLOW_DIRECT_EGRESS`` is read by ``startup_validation._env_flag``, whose
  true-set is exactly ``{1, true, yes}``.  ``CB_ALLOW_DIRECT_EGRESS=on`` is
  boolean-shaped, is what a reader coming from nginx or systemd would write, and
  is silently **false** — the operator gets the egress refusal they thought they
  had waived.  A generic "is it a bool" rule passes that value; this one does
  not.
* ``CB_AUTO_MIGRATE`` is read as ``!= "false"``, so every typo means *true*.
* ``CB_AIRGAP`` reaches pydantic's bool parser, which has a wider true-set than
  ``_env_flag`` and *raises* on anything outside it — which, before this module
  existed, escaped ``validate_config`` as a ``ValidationError`` traceback rather
  than as an error message.

Each rule returns the operator-facing message, or ``None`` when the value is
one the server can actually use.  Nothing here opens a socket or touches the
filesystem: an offline pass stays offline.
"""

from __future__ import annotations

import ipaddress
import json
from collections.abc import Callable
from urllib.parse import urlsplit

# startup_validation._env_flag: `os.environ.get(name, "").strip().lower() in
# {"1", "true", "yes"}`.  Anything else is false, with no error and no log line.
_ENV_FLAG_TRUE = ("1", "true", "yes")
_ENV_FLAG_FALSE = ("0", "false", "no", "")

# pydantic-settings' bool parser (pydantic.BaseModel bool coercion).  Wider than
# _env_flag, and it raises rather than defaulting when a value falls outside it.
_PYDANTIC_BOOL = (
    "0",
    "1",
    "true",
    "false",
    "yes",
    "no",
    "on",
    "off",
    "t",
    "f",
    "y",
    "n",
)


def _tcp_port(name: str, value: str) -> str | None:
    try:
        port = int(value.strip())
    except ValueError:
        return (
            f"{name}={value!r} is not a number. It must be a TCP port between 1 and 65535 "
            "(config.toml key `server.port`)."
        )
    if not 1 <= port <= 65535:
        return f"{name}={value!r} is outside the valid TCP port range 1-65535."
    return None


def _non_negative_int(name: str, value: str) -> str | None:
    try:
        parsed = int(value.strip())
    except ValueError:
        return f"{name}={value!r} is not a whole number."
    if parsed < 0:
        return f"{name}={value!r} must not be negative."
    return None


def _positive_int(name: str, value: str) -> str | None:
    error = _non_negative_int(name, value)
    if error:
        return error
    if int(value.strip()) == 0:
        return f"{name}={value!r} must be at least 1."
    return None


def _env_flag_bool(name: str, value: str) -> str | None:
    normalised = value.strip().lower()
    if normalised in _ENV_FLAG_TRUE or normalised in _ENV_FLAG_FALSE:
        return None
    return (
        f"{name}={value!r} is not a value this flag recognises. It is read with "
        f"`value.strip().lower() in {{{', '.join(repr(v) for v in _ENV_FLAG_TRUE)}}}`, so "
        f"{value!r} is silently treated as OFF — no error, no log line, and the behaviour "
        f"you were switching on stays switched off. Write one of "
        f"{', '.join(repr(v) for v in _ENV_FLAG_TRUE)} to enable it, or "
        f"{', '.join(repr(v) for v in _ENV_FLAG_FALSE if v)} to disable it."
    )


def _pydantic_bool(name: str, value: str) -> str | None:
    if value.strip().lower() in _PYDANTIC_BOOL:
        return None
    return (
        f"{name}={value!r} is not a boolean. This setting is parsed by pydantic, which "
        f"rejects the value outright rather than defaulting it, so the server fails to "
        f"start. Valid values: {', '.join(_PYDANTIC_BOOL)}."
    )


def _auto_migrate(name: str, value: str) -> str | None:
    """``main.lifespan`` reads this as ``!= "false"`` — every typo means *on*."""
    if value.strip().lower() in ("true", "false"):
        return None
    return (
        f"{name}={value!r} is read as `value.lower() != 'false'`, so it enables automatic "
        f"migrations — the opposite of what {value!r} was probably meant to say. Only the "
        "exact value 'false' disables them."
    )


def _url_scheme(*schemes: str) -> Callable[[str, str], str | None]:
    allowed = tuple(schemes)

    def rule(name: str, value: str) -> str | None:
        raw = value.strip()
        try:
            parts = urlsplit(raw)
        except ValueError as exc:
            return f"{name} is not a parsable URL: {exc}."
        # `+` separates the SQLAlchemy driver from the dialect: postgresql+psycopg2.
        scheme = parts.scheme.lower().split("+", 1)[0]
        if not scheme:
            return (
                f"{name}={raw!r} has no URL scheme. Expected one of "
                f"{', '.join(f'{s}://' for s in allowed)}."
            )
        if scheme not in allowed:
            return (
                f"{name} uses the {scheme!r} scheme, which this setting does not accept. "
                f"Expected one of {', '.join(f'{s}://' for s in allowed)}."
            )
        # memory:// carries no host by design; every other accepted scheme needs one.
        if scheme != "memory" and not parts.netloc and not parts.path:
            return f"{name}={raw!r} names no host."
        return None

    return rule


def _cidr_list(name: str, value: str) -> str | None:
    entries = _split_list(value)
    if not entries:
        return None
    bad: list[str] = []
    for entry in entries:
        try:
            ipaddress.ip_network(entry, strict=False)
        except ValueError:
            bad.append(entry)
    if bad:
        return (
            f"{name} contains {'entries' if len(bad) > 1 else 'an entry'} that "
            f"{'are' if len(bad) > 1 else 'is'} not a valid IP network: "
            f"{', '.join(repr(item) for item in bad)}. Use CIDR notation, e.g. "
            "'10.0.0.0/8,::1/128'."
        )
    return None


def _origin_list(name: str, value: str) -> str | None:
    entries = _split_list(value)
    bad = [entry for entry in entries if not _is_origin(entry)]
    if bad:
        return (
            f"{name} contains {', '.join(repr(item) for item in bad)}, which "
            f"{'are' if len(bad) > 1 else 'is'} not "
            f"{'origins' if len(bad) > 1 else 'an origin'}. A CORS origin is a scheme and "
            "host with no path, e.g. 'https://cb.example.com'. Values that are not JSON are "
            "split on commas, so a stray quote or trailing slash becomes an origin no "
            "browser will ever match."
        )
    return None


def _split_list(value: str) -> list[str]:
    """Split exactly the way ``Settings``' two list validators split."""
    raw = value.strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return [item.strip() for item in raw.split(",") if item.strip()]
    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]
    # parse_cors_origins keeps a non-list JSON scalar as a single entry.
    return [raw]


def _is_origin(value: str) -> bool:
    if value == "*":
        return True
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return False
    return not (parts.path or parts.query or parts.fragment)


# Only settings something in this codebase actually parses.  A rule for a
# setting nothing reads would be a rule with no failure mode behind it.
VALUE_RULES: dict[str, Callable[[str, str], str | None]] = {
    "CB_PORT": _tcp_port,
    "PORT": _tcp_port,
    "DB_POOL_SIZE": _non_negative_int,
    "DB_MAX_OVERFLOW": _non_negative_int,
    "UVICORN_WORKERS": _positive_int,
    "CB_ALLOW_DIRECT_EGRESS": _env_flag_bool,
    "CB_ALLOW_DEGRADED_DEPENDENCIES": _env_flag_bool,
    "CB_REQUIRE_TIMESCALE": _env_flag_bool,
    "CB_DISABLE_LEGACY_ALEMBIC_STAMP": _env_flag_bool,
    "CB_AUTO_MIGRATE": _auto_migrate,
    "CB_AIRGAP": _pydantic_bool,
    "AIRGAP": _pydantic_bool,
    "CB_UPDATE_CHECK": _pydantic_bool,
    "UPDATE_CHECK": _pydantic_bool,
    "CB_DB_URL": _url_scheme("postgresql", "postgres"),
    "DATABASE_URL": _url_scheme("postgresql", "postgres"),
    "CB_REDIS_URL": _url_scheme("redis", "rediss", "unix"),
    "REDIS_URL": _url_scheme("redis", "rediss", "unix"),
    "CB_RATE_LIMIT_STORAGE_URL": _url_scheme("redis", "rediss", "memory"),
    "RATE_LIMIT_STORAGE_URL": _url_scheme("redis", "rediss", "memory"),
    "CB_NATS_URL": _url_scheme("nats", "tls", "ws", "wss"),
    "CB_TRUSTED_PROXY_CIDRS": _cidr_list,
    "TRUSTED_PROXY_CIDRS": _cidr_list,
    "CORS_ORIGINS": _origin_list,
}


def validate_values(config: dict[str, str]) -> list[str]:
    """Every value-shape error in *config*, in a stable order.

    Settings that are absent are not this module's problem — a required setting
    that is missing is what ``startup_validation`` reports — so only values that
    are present and non-empty are judged.
    """
    errors: list[str] = []
    for name in sorted(VALUE_RULES):
        value = config.get(name)
        if value is None or not str(value).strip():
            continue
        error = VALUE_RULES[name](name, str(value))
        if error:
            errors.append(error)
    return errors
