"""Headless administration entrypoint (SRV-05).

``cb config validate`` and the packaged binary's ``--config-validate`` flag
both land here, as does the ``cb snapshot`` group the ``cb`` shell's backup and
restore paths shell out to.  Every rule this reports is *called*, not restated:
``app.core.startup_validation`` owns what a valid configuration is, and a
second copy of those rules is how a validator ends up passing a config the
server then refuses to boot with.

The same applies to *where* a setting comes from.  ``app.core.config_toml``
performs the file-vs-environment merge ``app.start`` performs at boot —
environment wins, config.toml fills the gaps — and this module calls it rather
than re-implementing it, because a validator reading a different configuration
than the server is worse than no validator at all.  ``ConfigReport.sources``
names the tier each setting was resolved from.

A ``config validate`` pass runs offline, and that is enforced rather than
promised: the pass refuses DNS resolution outright (see ``_refuse_dns``), so
nothing in it can reach Postgres, Redis, NATS or a name server.  The refusal is
scoped to that pass, not to the module — ``cb snapshot create`` below is the
third caller of ``services.db_backup.run_full_snapshot`` and must reach the
database.  Two tiers are therefore out of
reach, and the report says so instead of guessing:

* The JWT signing secret and the vault key both have a database tier
  (``AppSettings``) that only a running server can read — ``app.core.users``
  prefers it over ``CB_JWT_SECRET``, and ``settings_service`` generates one
  when it is absent.  The vault key additionally has a ``$CB_DATA_DIR/.env``
  tier, which *is* a file and so *is* read here.  A secret merely absent from
  the resolved configuration is a warning naming the tier that may still hold
  it; a secret that is *present* and bad is an error, because no later tier
  can rescue it.

  The vault key carries one rule beyond those two: ``vault_service`` accepts a
  key at *no* tier unless it is a real Fernet key, and a key that fails that
  test is dropped without an error — the server falls through to the next tier
  or generates a fresh key, and the operator's configured key is never the key
  in use.  That predicate is called here rather than restated, for the same
  reason as everything else in this module.
* ``CB_EGRESS_PROXY_URL`` is validated syntactically.  Its DNS/SSRF screen
  needs a resolver — and stalls on resolver timeouts on exactly the air-gapped
  hosts an offline validator is for — so it is deferred to startup, and a
  report that deferred it says which host it deferred.

The database tier is reachable on demand rather than never: ``--database``
opts one pass into connecting, and only that pass — the default is still the
offline one described above, and ``_refuse_dns`` still holds for the gates.
What the tier is worth is not the two values it supplies but the two conflicts
only it can see: ``app.core.users`` prefers ``AppSettings.jwt_secret`` over
``CB_JWT_SECRET``, and ``vault_service.load_vault_key`` cross-checks an
environment vault key against ``app_settings.vault_key_hash`` and *drops* it
when they disagree.  Either way the operator's configured value is not the one
in use, and no offline pass can tell them so.

``--set NAME=VALUE`` is the fourth tier, and the highest: it overrides the
environment, which overrides config.toml.  It takes either an environment
variable name or the config.toml key that maps to one (``--set
server.port=9090``), so the precedence order can be exercised from one end to
the other without editing a file the operator may not be able to write.

Finally, "valid" now includes the *shape* of a value, not only the presence of
one: see ``app.scripts.config_values``.  A validator that passes
``server.port = "not-a-port"`` because nothing it calls happens to parse the
port is a validator that cannot be trusted with the answer it gives.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import socket
import sys
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.startup_validation import (
    allow_degraded_dependencies,
    validate_core_dependencies,
    validate_secret_value,
)
from app.scripts.config_values import validate_values
from app.services.backup.verify import SnapshotProblem, verify_archive

_REDACTED = "…redacted…"

# Every setting the offline validator recognises.  SRV-05 asks for one
# documented precedence order — CLI flag, then environment, then config file,
# then database.  The first three are resolvable without a running server and
# are all honoured here; the database tier is not, and the two settings that
# have one (see the module docstring) are reported as such.  Entries that share
# a setting (CB_* and the unprefixed legacy name) are both listed because
# either one is what the operator actually typed.
_KNOWN_SETTINGS = (
    "CB_JWT_SECRET",
    "CB_VAULT_KEY",
    "CB_DB_URL",
    "DATABASE_URL",
    "CB_REDIS_URL",
    "REDIS_URL",
    "CB_RATE_LIMIT_STORAGE_URL",
    "RATE_LIMIT_STORAGE_URL",
    "CB_EGRESS_PROXY_URL",
    "EGRESS_PROXY_URL",
    "CB_ALLOW_DIRECT_EGRESS",
    "CB_ALLOW_DEGRADED_DEPENDENCIES",
    "CB_TRUSTED_PROXY_CIDRS",
    "TRUSTED_PROXY_CIDRS",
    "CORS_ORIGINS",
    # Settings no gate reads but something at startup parses.  They are listed
    # so the report names the tier each came from, which is the half of a
    # value-shape error an operator cannot work out for themselves: knowing
    # CB_PORT is not a number is no help until you know which of four files set
    # it.  app.scripts.config_values holds the rules.
    "CB_HOST",
    "CB_PORT",
    "PORT",
    "CB_NATS_URL",
    "DB_POOL_SIZE",
    "DB_MAX_OVERFLOW",
    "UVICORN_WORKERS",
    "CB_AIRGAP",
    "AIRGAP",
    "CB_UPDATE_CHECK",
    "UPDATE_CHECK",
    "CB_AUTO_MIGRATE",
    "CB_REQUIRE_TIMESCALE",
    "CB_DISABLE_LEGACY_ALEMBIC_STAMP",
    # Not settings the gates read, but they decide which files the tiers above
    # are read from, so an operator debugging a surprising verdict needs them.
    "CB_CONFIG",
    "CB_DATA_DIR",
    "CB_ALEMBIC_INI",
)

_SECRET_SETTINGS = frozenset({"CB_JWT_SECRET", "CB_VAULT_KEY"})

# The same labels and minimum length validate_startup_secrets() applies.  It
# checks both secrets in one call and has no per-secret entry point, and this
# module has to classify each secret separately because they have different
# non-environment tiers, so its primitive is called once per secret instead.
# test_secret_rules_match_the_startup_gate fails if these ever drift from it.
_JWT_SECRET_LABEL = "JWT/session signing secret"
_VAULT_KEY_LABEL = "Vault encryption key"
_SECRET_MIN_LENGTH = 32

# vault_service.load_vault_key() reads this out of $CB_DATA_DIR/.env after the
# environment and before the database.
_VAULT_KEY_IN_ENV_FILE = re.compile(r"^CB_VAULT_KEY\s*=\s*(.+)$", re.MULTILINE)


def _vault_service_accepts_key(key: str) -> bool:
    """Whether vault_service would accept *key* — its predicate, not a copy of it.

    ``load_vault_key()`` guards every one of its three tiers with
    ``_is_valid_fernet_key``, and a key that fails it is discarded *silently*:
    the loader logs and falls through, so the Phase-7 startup gate in main.py
    only ever sees the key that survived, and a configured-but-unusable key
    reaches no gate at all.  The validator has to apply the rule itself or its
    verdict is about a key the server is not using.

    The name is private and this module owns no part of vault_service, so it is
    imported as-is: re-deriving the base64/32-byte rule here would be exactly
    the second copy of a validity rule this module exists to avoid, and it would
    stop tracking the loader the day either side changed.  If it is ever
    promoted to a public name, call that instead.

    Imported inside the function because vault_service pulls in SQLAlchemy and
    the credential vault at import time, which an offline `config validate` pass
    otherwise has no use for.
    """
    from app.services.vault_service import _is_valid_fernet_key

    return _is_valid_fernet_key(key)


# Stand-ins for the live handles validate_core_dependencies() would be given at
# startup.  Passing "connected" here is deliberate: reachability is a runtime
# property, so the offline validator asserts only the configuration half of the
# gate and leaves Redis/NATS liveness to /readyz.
_ASSUME_CONNECTED = object()


@dataclass(frozen=True)
class ResolvedConfig:
    """One configuration, merged across every tier this process can read.

    ``values`` holds raw values (secrets included) and must be redacted before
    it is printed; ``sources`` maps a setting to the tier it came from and is
    always safe to show.
    """

    values: dict[str, str]
    sources: dict[str, str]
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass
class ConfigReport:
    """The outcome of one offline validation pass.

    ``sources`` maps a setting name to where its value came from — never to the
    value itself, so a report is always safe to print or paste into an issue.
    """

    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    sources: dict[str, str] = field(default_factory=dict)

    def error(self, message: str) -> None:
        self.errors.append(message)
        self.ok = False

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def _redact(name: str, value: str) -> str:
    """Render a value for human eyes, with anything credential-shaped removed."""
    if name in _SECRET_SETTINGS:
        return _REDACTED
    # Connection strings carry passwords in their userinfo: redis://user:pw@host.
    if "://" in value and "@" in value.split("://", 1)[1].split("/", 1)[0]:
        scheme, rest = value.split("://", 1)
        _userinfo, host = rest.split("@", 1)
        return f"{scheme}://{_REDACTED}@{host}"
    return value


def _split_joined_errors(message: str) -> list[str]:
    """Undo validate_core_dependencies()'s "; ".join of its error list.

    The join is lossy: the egress message itself reads "...controlled egress;
    set CB_ALLOW_DIRECT_EGRESS=true...", so splitting on every "; " tears one
    error in half.  Each real error opens with a capitalised token
    (Rate-limit, CB_EGRESS_PROXY_URL, Redis, NATS) while a continuation clause
    does not, which is enough to put the boundaries back.
    """
    return re.split(r"; (?=[^a-z])", message)


def _config_toml_candidates(env: Mapping[str, str]) -> list[Path]:
    """The files load_config_toml() searches, in its order.

    Only the search is mirrored; the parsing and the merge stay in
    config_toml.py, which is called with the path this picks.  A path is needed
    separately because the loader reports how many settings it applied, not
    which file it applied them from, and a report that cannot name the file is
    no help to an operator with a config.toml in more than one location.
    """
    candidates = [Path(env.get("CB_CONFIG", "")), Path("/etc/circuit-breaker/config.toml")]
    try:
        candidates.append(Path.home() / ".config" / "circuitbreaker" / "config.toml")
    except RuntimeError:
        # No resolvable home directory.  load_config_toml() raises here too and
        # start.py swallows it, so there is no file tier to report either way.
        pass
    candidates.append(Path.cwd() / "config.toml")
    return candidates


def _discover_config_toml(env: Mapping[str, str], config_path: str | Path | None) -> Path | None:
    if config_path is not None:
        explicit = Path(config_path)
        return explicit if explicit.is_file() else None
    for candidate in _config_toml_candidates(env):
        if candidate.is_file():
            return candidate
    return None


def _config_toml_layer(env: Mapping[str, str], path: Path) -> dict[str, str]:
    """Return the settings ``path`` contributes on top of ``env``.

    load_config_toml() writes into os.environ and skips any name already set
    there, which is exactly the precedence start.py boots with, so it is called
    against a temporarily bound copy of ``env`` and the additions are read back
    out.  Reproducing the key map here instead would be a second copy of the
    thing this module exists to avoid.
    """
    from app.core.config_toml import load_config_toml

    saved_environ = dict(os.environ)
    os.environ.clear()
    os.environ.update(env)
    try:
        load_config_toml(path)
        return {name: value for name, value in os.environ.items() if name not in env}
    finally:
        os.environ.clear()
        os.environ.update(saved_environ)


def _vault_key_env_file(env: Mapping[str, str]) -> Path:
    """The ``$CB_DATA_DIR/.env`` vault_service.load_vault_key() reads second.

    vault_service resolves this once at import time from the environment the
    process started in, so it cannot be asked about a different one; the path
    rule (CB_DATA_DIR, else ./data) is the same rule.
    """
    data_dir = Path(env.get("CB_DATA_DIR") or (Path.cwd() / "data")).expanduser()
    return data_dir / ".env"


def _vault_key_from_env_file(path: Path) -> str | None:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = _VAULT_KEY_IN_ENV_FILE.search(content)
    if not match:
        return None
    return match.group(1).strip() or None


# app_settings is a singleton row (id=1); every reader in the codebase reads it
# that way.  Selected by name rather than with SELECT * so a schema this build
# does not know about cannot change what is read.
_APP_SETTINGS_QUERY = "SELECT jwt_secret, vault_key, vault_key_hash FROM app_settings WHERE id = 1"

# Long enough to cross a LAN or a container network, short enough that a
# validator pointed at a database that is not there fails while the operator is
# still watching.
_DATABASE_TIER_TIMEOUT_SECONDS = 5


def _apply_database_tier(
    values: dict[str, str],
    sources: dict[str, str],
    errors: list[str],
    warnings: list[str],
) -> None:
    """Read the two settings that have an ``AppSettings`` tier, and the conflicts.

    Opt-in (``--set`` aside, this is the only part of a pass that opens a
    socket) because the whole point of the offline default is that it works on
    a host where the database is down — which is frequently *why* someone is
    validating a configuration.  When it is asked for, an unreachable database
    is an error rather than a warning: the operator asked a question this pass
    then could not answer.

    Both settings are read the way their readers read them:

    * ``app.core.users`` prefers ``AppSettings.jwt_secret`` and falls back to
      ``CB_JWT_SECRET``, so a database value shadows the environment.
    * ``vault_service.load_vault_key`` accepts the environment key only when it
      matches ``app_settings.vault_key_hash``; on a mismatch it logs and falls
      through to the file and database tiers, so the configured key is not the
      key in use.  That check is on the *environment* tier alone — the
      ``$CB_DATA_DIR/.env`` key is not hash-checked — and it is reproduced with
      that same scope here.
    """
    url = (values.get("CB_DB_URL") or values.get("DATABASE_URL") or "").strip()
    if not url:
        errors.append(
            "--database was requested but neither CB_DB_URL nor DATABASE_URL is set, so "
            "there is no database to read the AppSettings tier from."
        )
        return

    try:
        row = _read_app_settings(url)
    except Exception as exc:  # noqa: BLE001 - every driver failure is one operator message
        errors.append(
            f"--database was requested but the database could not be read: "
            f"{_redact_connection_error(exc)}. Re-run without --database to validate the "
            "file, environment and command-line tiers offline."
        )
        return

    if row is None:
        warnings.append(
            "The database is reachable but has no app_settings row yet, so the database "
            "tier is empty. That is the expected state before first-run setup completes."
        )
        return

    db_jwt_secret, db_vault_key, db_vault_key_hash = row

    configured_jwt = (values.get("CB_JWT_SECRET") or "").strip()
    if (db_jwt_secret or "").strip():
        if not configured_jwt:
            values["CB_JWT_SECRET"] = str(db_jwt_secret).strip()
            sources["CB_JWT_SECRET"] = "database (app_settings.jwt_secret)"
        elif str(db_jwt_secret).strip() != configured_jwt:
            warnings.append(
                "CB_JWT_SECRET is set, but app_settings.jwt_secret holds a different value "
                "and app.core.users prefers the database column — so the environment value "
                "signs nothing. Clear the database column to make the environment "
                "authoritative, or drop CB_JWT_SECRET so the configuration says what is "
                "actually in use."
            )
    elif not configured_jwt:
        warnings.append(
            "Neither CB_JWT_SECRET nor app_settings.jwt_secret is set. The server generates "
            "a signing secret on first use, which is fine for a fresh install and means "
            "every session is invalidated if that row is ever lost."
        )

    vault_key = (values.get("CB_VAULT_KEY") or "").strip()
    vault_source = sources.get("CB_VAULT_KEY", "")
    if vault_key and vault_source == "environment" and (db_vault_key_hash or "").strip():
        if not _matches_vault_key_hash(vault_key, str(db_vault_key_hash).strip()):
            errors.append(
                "CB_VAULT_KEY does not match app_settings.vault_key_hash. "
                "vault_service.load_vault_key() treats an environment key that fails this "
                "cross-check as stale — it logs a warning and falls through to "
                f"{_vault_key_env_file(values)} and then to the database column — so this "
                "key decrypts nothing and the key actually in use is somewhere else. This "
                "is what a CB_VAULT_KEY left behind by an automatic key rotation looks "
                "like."
            )
    elif not vault_key and (db_vault_key or "").strip():
        values["CB_VAULT_KEY"] = str(db_vault_key).strip()
        sources["CB_VAULT_KEY"] = "database (app_settings.vault_key)"
        warnings.append(
            "The vault key was resolved from the app_settings.vault_key column, which "
            "stores it in plaintext (CWE-312). The server migrates it to "
            f"{_vault_key_env_file(values)} on the next start and clears the column."
        )


def _read_app_settings(url: str) -> tuple[str | None, str | None, str | None] | None:
    """One short-lived connection, one row, no ORM and no shared engine.

    ``app.db.session`` builds its engine from the environment at import time,
    which is the environment this process happens to have rather than the one
    being validated; a pass that asked it for a connection would be reading a
    different database than the report names.
    """
    from sqlalchemy import create_engine, text

    engine = create_engine(
        url,
        connect_args={"connect_timeout": _DATABASE_TIER_TIMEOUT_SECONDS},
        pool_pre_ping=False,
    )
    try:
        with engine.connect() as connection:
            result = connection.execute(text(_APP_SETTINGS_QUERY)).first()
        if result is None:
            return None
        return (result[0], result[1], result[2])
    finally:
        engine.dispose()


def _matches_vault_key_hash(key: str, stored_hash: str) -> bool:
    """``vault_service``'s own cross-check: SHA-256 of the key, compared constant-time."""
    import hashlib
    import hmac as _hmac

    return _hmac.compare_digest(hashlib.sha256(key.encode()).hexdigest(), stored_hash)


def _redact_connection_error(exc: Exception) -> str:
    """A driver error with the connection URL's password taken out of it.

    SQLAlchemy puts the URL in the message of most connection failures, and the
    URL carries the database password in its userinfo.  This report is meant to
    be pasteable into an issue.
    """
    message = f"{type(exc).__name__}: {exc}"
    return re.sub(r"(?P<scheme>\w+)://[^\s/@]*:[^\s/@]*@", rf"\g<scheme>://{_REDACTED}@", message)


class OverrideError(ValueError):
    """A ``--set`` argument that names nothing the server would read."""


def parse_overrides(assignments: Sequence[str]) -> dict[str, str]:
    """Turn ``--set`` arguments into the environment names the server reads.

    Both spellings are accepted, because both are what an operator has in front
    of them: the environment variable itself (``CB_PORT=9090``) and the
    config.toml key that maps to it (``server.port=9090``).  The mapping is
    ``config_toml``'s own — imported rather than restated, for the reason the
    module docstring gives about second copies — so ``--set`` can never name a
    key the file tier does not have.

    ``_KEY_MAP`` is private, and this is the second private name this module
    borrows on purpose (see ``_vault_service_accepts_key``): re-listing the
    seventeen key/variable pairs here would drift the day either side changed,
    and a ``--set`` that silently disagreed with the file tier is worse than no
    ``--set`` at all.
    """
    from app.core.config_toml import _KEY_MAP

    overrides: dict[str, str] = {}
    for assignment in assignments:
        if "=" not in assignment:
            raise OverrideError(
                f"--set {assignment!r} is not an assignment. Write --set NAME=VALUE, "
                "using either an environment variable name (CB_PORT=9090) or the "
                "config.toml key it maps to (server.port=9090)."
            )
        name, value = assignment.split("=", 1)
        name = name.strip()
        if not name:
            raise OverrideError(f"--set {assignment!r} names no setting.")
        if "." in name:
            mapped = _KEY_MAP.get(name)
            if mapped is None:
                raise OverrideError(
                    f"--set {name!r} is not a config.toml key this server reads. "
                    f"Known keys: {', '.join(sorted(_KEY_MAP))}."
                )
            name = mapped
        overrides[name] = value
    return overrides


def resolve_config(
    env: Mapping[str, str],
    *,
    config_path: str | Path | None = None,
    overrides: Mapping[str, str] | None = None,
    database: bool = False,
) -> ResolvedConfig:
    """Merge every configuration tier, in the server's precedence order.

    Command line (``--set``) first, then environment, then config.toml, then —
    for the vault key alone — ``$CB_DATA_DIR/.env``.  The database tier is read
    last and only when *database* is true; see ``_apply_database_tier``.
    """
    values = {name: str(value) for name, value in env.items()}
    sources = {name: "environment" for name in _KNOWN_SETTINGS if name in values}
    errors: list[str] = []
    warnings: list[str] = []

    # Highest tier, so it is applied before the file tier is even computed:
    # _config_toml_layer() only contributes names that are not already set,
    # which is precisely how the server resolves file-under-environment, and an
    # override that arrived afterwards would be a different precedence order
    # than the one being reported.
    for name, value in (overrides or {}).items():
        values[name] = str(value)
        sources[name] = "command line (--set)"

    toml_path = _discover_config_toml(values, config_path)
    if toml_path is not None:
        try:
            contributed = _config_toml_layer(values, toml_path)
        except (OSError, ValueError) as exc:
            # tomllib.TOMLDecodeError is a ValueError.  start.py swallows this
            # and boots without the file; a validator must say it happened,
            # because every setting the file was meant to supply is now missing.
            errors.append(f"config.toml at {toml_path} could not be read: {exc}")
        else:
            source = f"config.toml ({toml_path})"
            for name, value in contributed.items():
                values[name] = value
                if name in _KNOWN_SETTINGS:
                    sources[name] = source

    if not (values.get("CB_VAULT_KEY") or "").strip():
        env_file = _vault_key_env_file(values)
        file_key = _vault_key_from_env_file(env_file)
        if file_key:
            values["CB_VAULT_KEY"] = file_key
            sources["CB_VAULT_KEY"] = str(env_file)

    if database:
        _apply_database_tier(values, sources, errors, warnings)

    return ResolvedConfig(
        values=values,
        sources=sources,
        errors=tuple(errors),
        warnings=tuple(warnings),
    )


@contextmanager
def _bound_environment(env: Mapping[str, str]) -> Iterator[None]:
    """Point the process environment and the settings singleton at ``env``.

    startup_validation's gates read ``os.environ`` and the shared ``settings``
    object rather than taking a mapping, so binding both for the duration of a
    pass is what lets this module call those gates instead of copying them.
    Both are restored on the way out, including when a rule raises.
    """
    from app.core.config import Settings, settings

    # Snapshot first: env is frequently os.environ itself, and clearing the
    # mapping before copying out of it would validate an empty environment.
    replacement = {key: str(value) for key, value in env.items()}
    saved_environ = dict(os.environ)
    saved_fields = dict(settings.__dict__)
    os.environ.clear()
    os.environ.update(replacement)
    try:
        # _env_file=None: a stray .env in the working directory must not change
        # the verdict on the environment the operator asked about.
        settings.__dict__.update(Settings(_env_file=None).__dict__)  # type: ignore[call-arg]
        yield
    finally:
        settings.__dict__.clear()
        settings.__dict__.update(saved_fields)
        os.environ.clear()
        os.environ.update(saved_environ)


@contextmanager
def _refuse_dns() -> Iterator[list[str]]:
    """Make name resolution impossible for the duration of a pass.

    ``validate_egress_proxy()`` reaches ``validate_outbound_url()``, whose SSRF
    screen resolves the proxy hostname.  On an air-gapped host — the one place
    an offline validator earns its keep — that stalls on resolver timeouts and
    can fail a perfectly good proxy.  EGRESS_PROXY_POLICY already sets
    ``allow_unresolved_hostname``, so refusing the lookup leaves the syntactic
    checks (scheme, userinfo, port, host) and the SSRF screen on literal
    addresses intact and defers only the part that needs a network.

    Yields the list of hostnames a pass wanted resolved, so the report can name
    what it deferred rather than quietly skipping it.

    Like ``_bound_environment`` above this is process-global while it is held,
    which a single-threaded CLI pass can afford and is the point: the module's
    "opens no socket" claim becomes a mechanism instead of a promise.
    """
    deferred: list[str] = []
    saved = socket.getaddrinfo

    def _refuse(host: Any, *args: Any, **kwargs: Any) -> Any:
        deferred.append(str(host))
        raise socket.gaierror(socket.EAI_NONAME, "offline validation does not resolve hostnames")

    socket.getaddrinfo = _refuse
    try:
        yield deferred
    finally:
        socket.getaddrinfo = saved


def validate_config(
    config: ResolvedConfig | Mapping[str, str],
    *,
    config_path: str | Path | None = None,
    overrides: Mapping[str, str] | None = None,
    database: bool = False,
) -> ConfigReport:
    """Validate a configuration against the same rules the server enforces at startup.

    Accepts either a raw mapping (typically ``os.environ``), which is resolved
    across the tiers first, or an already-resolved configuration.
    """
    resolved = (
        config
        if isinstance(config, ResolvedConfig)
        else resolve_config(config, config_path=config_path, overrides=overrides, database=database)
    )
    env = resolved.values
    report = ConfigReport(sources=dict(resolved.sources))
    for file_error in resolved.errors:
        report.error(file_error)
    for resolution_warning in resolved.warnings:
        report.warn(resolution_warning)

    # Before anything reads a value: a setting whose *shape* is wrong is not a
    # setting the gates below can judge, and one of them (pydantic's bool) will
    # raise rather than report if it is handed one.
    value_errors = validate_values(env)
    for value_error in value_errors:
        report.error(value_error)

    jwt_secret = (env.get("CB_JWT_SECRET") or "").strip()
    if jwt_secret:
        jwt_error = validate_secret_value(
            _JWT_SECRET_LABEL, jwt_secret, min_length=_SECRET_MIN_LENGTH
        )
        if jwt_error:
            report.error(jwt_error)
    else:
        # Not an error: app.core.users reads AppSettings.jwt_secret from the
        # database first and only falls back to CB_JWT_SECRET, and
        # settings_service generates one on first use — so a native install
        # whose env file never mentions the variable (packaging/postinstall.sh
        # writes no CB_JWT_SECRET) is correctly configured.  Offline, that tier
        # cannot be read, so this is reported as unconfirmed rather than wrong.
        report.warn(
            "CB_JWT_SECRET is unset or empty; the server resolves the signing secret from the "
            "AppSettings.jwt_secret database column first and generates one there when "
            "it is absent, so this may be fine — it cannot be confirmed without the "
            "database.  Check `SELECT jwt_secret IS NOT NULL FROM app_settings`, or set "
            "CB_JWT_SECRET to pin the secret in the environment."
        )

    vault_key = (env.get("CB_VAULT_KEY") or "").strip()
    if vault_key:
        vault_error = validate_secret_value(
            _VAULT_KEY_LABEL, vault_key, min_length=_SECRET_MIN_LENGTH
        )
        if vault_error:
            report.error(vault_error)
        elif not _vault_service_accepts_key(vault_key):
            # Long enough and not a placeholder, so the shared secret rules pass
            # it — but vault_service rejects it at whichever tier it came from
            # and moves on to the next one without raising, which is why the
            # Phase-7 startup gate never sees it either.
            tier = resolved.sources.get("CB_VAULT_KEY", "the resolved configuration")
            report.error(
                f"{_VAULT_KEY_LABEL} (from {tier}) is not a valid Fernet key: it must be "
                "32 random bytes, URL-safe-base64 encoded — the 44-character output of "
                '`python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"`.  vault_service.load_vault_key() '
                "requires this at every tier and discards a key that fails it without an "
                "error, so the server would start on a later tier's key or generate a new "
                "one and this key would never be used"
            )
    else:
        # Same shape as the JWT secret: env -> $CB_DATA_DIR/.env -> AppSettings.
        # The first two tiers were searched during resolution and came up empty;
        # the third cannot be searched from here.
        report.warn(
            "CB_VAULT_KEY is unset or empty and no key was found in "
            f"{_vault_key_env_file(env)}; "
            "the server would fall back to the AppSettings vault key, which cannot be "
            "read offline.  If it has none either, encrypted integration secrets are "
            "unavailable until the vault key is restored or OOBE generates one"
        )

    if value_errors:
        # Settings() is constructed inside _bound_environment and raises on a
        # value its own parsers reject.  Reporting the value errors and stopping
        # is the difference between an operator reading a sentence that names
        # the setting and an operator reading a pydantic traceback.
        report.warn(
            "The dependency gates were not run: they read the settings above, and the "
            f"{'values' if len(value_errors) > 1 else 'value'} reported as invalid "
            "cannot be read. Fix those and re-run to see the rest of the report."
        )
        return report

    with _bound_environment(env), _refuse_dns() as deferred_hostnames:
        if allow_degraded_dependencies():
            report.warn(
                "CB_ALLOW_DEGRADED_DEPENDENCIES is set; every dependency gate below "
                "is waived at startup, including shared rate-limit storage"
            )
        try:
            # No await in this coroutine reaches the network — it inspects the
            # configuration and the two handles it is given, and _refuse_dns()
            # holds that true even for the egress proxy's SSRF screen.
            asyncio.run(validate_core_dependencies(_ASSUME_CONNECTED, True))
        except RuntimeError as exc:
            for dependency_error in _split_joined_errors(str(exc)):
                report.error(dependency_error)

    for hostname in dict.fromkeys(deferred_hostnames):
        report.warn(
            f"'{hostname}' was checked syntactically only; resolving it would need a "
            "network, so the DNS and SSRF screen on that host runs when the server starts"
        )

    return report


def _cmd_config_validate(
    config_path: str | None = None,
    overrides: Sequence[str] = (),
    *,
    database: bool = False,
) -> int:
    try:
        parsed_overrides = parse_overrides(overrides)
    except OverrideError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    resolved = resolve_config(
        os.environ,
        config_path=config_path,
        overrides=parsed_overrides,
        database=database,
    )
    report = validate_config(resolved)

    if report.sources:
        print("Resolved settings:")
        for name, source in sorted(report.sources.items()):
            print(f"  {name} = {_redact(name, resolved.values.get(name, ''))}  (from {source})")

    for warning in report.warnings:
        print(f"warning: {warning}")
    for error in report.errors:
        print(f"error: {error}", file=sys.stderr)

    if report.ok:
        print("configuration valid")
        return 0
    print(f"configuration INVALID: {len(report.errors)} error(s)", file=sys.stderr)
    return 1


def _cli_session() -> Any:
    """A synchronous session for CLI use.

    Imported lazily on purpose: ``cb config validate`` must stay offline, and importing
    the session module builds the engine.
    """
    from app.db.session import SessionLocal

    return SessionLocal()


async def _run_full_snapshot(db: Any) -> Path:
    """The third caller of the one orchestrator, never a second implementation.

    Lazy for the same reason as ``_cli_session``, and for one more: ``services.db_backup``
    reads ``BACKUP_DIR`` from the environment at import time, so ``--out`` can only take
    effect if the import happens after this module has set it.
    """
    from app.services.db_backup import run_full_snapshot

    return await run_full_snapshot(db)


def _cmd_snapshot_create(out: str | None) -> int:
    if out:
        os.environ["BACKUP_DIR"] = out

    try:
        with _cli_session() as db:
            path = asyncio.run(_run_full_snapshot(db))
    except Exception as exc:  # noqa: BLE001 - the CLI is the boundary; report, do not raise
        print(f"snapshot failed: {exc}", file=sys.stderr)
        return 1

    # The path alone on stdout: `cb backup` captures this.
    print(path)
    return 0


def _cmd_snapshot_encrypt(archive: str, recipient: str) -> int:
    """Write the off-host derivative of *archive*, encrypted to one age recipient.

    Deliberately the same function the S3 upload path calls.  B3's promise is that
    nothing leaving the host carries the vault key in the clear, and a second
    encryptor reachable from the CLI would be a second place for that to stop being
    true.

    It exists so the promise is *exercisable*.  ``cb restore --identity`` could
    already read the encrypted format, but only the scheduled S3 job could produce
    one — so the round trip the release blocker turns on had no caller outside a
    configured bucket, and neither an operator nor a verification tier could take
    it.  The private identity stays with the operator: this takes a public
    recipient and never sees the key that opens the result.
    """
    from app.services.backup.age_encryption import encrypt_for_upload
    from app.services.backup.snapshot import BackupError

    source = Path(archive)
    if not source.is_file():
        print(f"snapshot not found: {archive}", file=sys.stderr)
        return 1

    try:
        encrypted = encrypt_for_upload(source, recipient)
    except BackupError as exc:
        print(f"encryption failed: {exc}", file=sys.stderr)
        return 1

    # The path alone on stdout, exactly as `snapshot create` does: `cb backup`
    # captures this line.
    print(encrypted)
    return 0


# RC-04's minimum directly supported source version, from
# docs/release/1.0.0-compatibility-policy.md ("Database and source-release
# compatibility").  A restore replays a dump and then migrates it forward, so an
# archive older than this is the same upgrade the table marks *Upgrade-only
# until proven* — not rejected, and so not something to refuse a recovery over,
# but not something to let an operator discover afterwards either.
#
# The value is duplicated from a document the container does not ship, which is
# why test_cli_snapshot_policy reads that table and asserts the two agree: a
# policy floor that only exists in prose is a floor nothing enforces, and one
# that only exists in code is one nobody can find.
_MINIMUM_RESTORABLE_SOURCE_VERSION = "0.3.5"


def _version_below_floor(archive_version: str, floor: str) -> bool:
    """Compare release parts only, exactly as the verifier's own skew check does."""
    from app.services.backup.verify import _version_tuple

    parts = _version_tuple(archive_version)
    return bool(parts) and parts < _version_tuple(floor)


def _cmd_snapshot_verify(archive: str) -> int:
    installed_version = os.environ.get("CB_VERSION")
    try:
        manifest = verify_archive(Path(archive), installed_version=installed_version)
    except SnapshotProblem as problem:
        print(str(problem), file=sys.stderr)
        return 1

    # Skipped when CB_VERSION is empty for the same reason the verifier's
    # newer-than-this-build refusal is: that is the signal `cb restore --force`
    # sends, and a --force that waived one version gate but not the other would
    # be two policies wearing one flag.
    archive_version = str(manifest.get("cb_version", ""))
    if installed_version and _version_below_floor(
        archive_version, _MINIMUM_RESTORABLE_SOURCE_VERSION
    ):
        print(
            f"warning: this snapshot is from Circuit Breaker {archive_version}, below the "
            f"minimum directly supported source version "
            f"({_MINIMUM_RESTORABLE_SOURCE_VERSION}). The restore itself is sound — the "
            "archive verified — but the migrations that then run on it are an upgrade path "
            "this release has not proven. Stage the upgrade through "
            f"{_MINIMUM_RESTORABLE_SOURCE_VERSION} instead, or verify the result before "
            "relying on it.",
            file=sys.stderr,
        )

    print(json.dumps(manifest, indent=2))
    return 0


# ── SRV-06: the administration journeys ──────────────────────────────────────
#
# Every command below is a thin shell around app.scripts.cli_admin: argument
# shapes and printing live here, the operations live there, and the operations
# call the services the API calls.  The split is what lets the same journey be
# tested against a real database without a shell.


def _admin_session() -> Any:
    """A session for the mutating admin commands.

    Separate from ``_cli_session`` in name only, so the lazy-import reason
    stated there is not accidentally read as applying to a command that must
    reach the database.
    """
    return _cli_session()


def _emit(payload: Any, as_json: bool, render: Any) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        render()


def _run_admin(handler: Any) -> int:
    """Run one admin command, turning its failures into messages.

    Nothing below this point may reach the operator as a traceback: an
    administration CLI that answers a mistyped email address with a stack trace
    is one an operator cannot use during an incident.  ``AdminError`` carries
    the exit code the failure deserves; anything else is a bug in this process
    and is reported with its type so it can be triaged, still without a
    traceback on the operator's terminal.
    """
    from app.scripts.cli_admin import EXIT_FAILED, AdminError

    try:
        return handler()  # type: ignore[no-any-return]
    except AdminError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code
    except Exception as exc:  # noqa: BLE001 - the CLI is the boundary
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_FAILED


def _cmd_migrate_status(as_json: bool) -> int:
    from app.scripts.cli_admin import EXIT_OK, EXIT_PENDING, migration_status

    def run() -> int:
        status = migration_status()
        payload = {
            "current": list(status.current),
            "head": list(status.head),
            "pending": list(status.pending),
            "up_to_date": status.up_to_date,
        }

        def render() -> None:
            print(f"database revision: {', '.join(status.current) or '(none — never migrated)'}")
            print(f"this build's head: {', '.join(status.head) or '(none)'}")
            if status.up_to_date:
                print("schema up to date")
            else:
                print(f"pending migrations: {len(status.pending)}")
                for revision in status.pending:
                    print(f"  {revision}")
                print("apply them with: cb migrate upgrade")

        _emit(payload, as_json, render)
        return EXIT_OK if status.up_to_date else EXIT_PENDING

    return _run_admin(run)


def _cmd_migrate_upgrade() -> int:
    from app.scripts.cli_admin import EXIT_OK, apply_migrations, migration_status

    def run() -> int:
        before = migration_status()
        if before.up_to_date:
            print("schema already up to date; nothing to do")
            return EXIT_OK
        print(f"applying {len(before.pending)} migration(s)…")
        apply_migrations()
        after = migration_status()
        print(f"schema at {', '.join(after.current) or '(none)'}")
        return EXIT_OK

    return _run_admin(run)


def _print_token_secret(raw_token: str) -> None:
    """The one and only place a token value is rendered.

    It goes to stdout so `TOKEN=$(cb token create … | tail -n1)` works, and the
    surrounding explanation goes to stderr so it cannot end up inside the
    captured value.  Nothing stores it: the row holds a salted HMAC, and there
    is no command that reads a token back.
    """
    print(
        "This value is shown once and is not recoverable — store it now.",
        file=sys.stderr,
    )
    print(raw_token)


def _cmd_token_create(args: argparse.Namespace) -> int:
    from app.scripts.cli_admin import EXIT_OK, create_api_token, resolve_actor, resolve_scopes

    def run() -> int:
        scopes = resolve_scopes(args.scopes or [], args.preset)
        expires_in_days = None if args.never_expires else args.expires_in_days
        with _admin_session() as db:
            actor = resolve_actor(db, args.actor)
            raw_token, summary = create_api_token(
                db,
                actor,
                label=args.label,
                scopes=scopes,
                expires_in_days=expires_in_days,
            )

        def render() -> None:
            print(f"created API token {summary.id} ({summary.label})")
            print(f"  scopes:  {', '.join(summary.scopes)}")
            print(f"  expires: {summary.expires_at or 'never'}")
            _print_token_secret(raw_token)

        _emit({**summary.as_dict(), "token": raw_token}, args.json, render)
        return EXIT_OK

    return _run_admin(run)


def _cmd_token_list(as_json: bool) -> int:
    from app.scripts.cli_admin import EXIT_OK, list_api_tokens

    def run() -> int:
        with _admin_session() as db:
            tokens = list_api_tokens(db)

        def render() -> None:
            if not tokens:
                print("no API tokens")
                return
            print(f"{'ID':>4}  {'LABEL':<28} {'SCOPES':<28} {'EXPIRES':<26} LAST USED")
            for token in tokens:
                expiry = token.expires_at or "never"
                if token.expired:
                    expiry = f"{expiry} (EXPIRED)"
                print(
                    f"{token.id:>4}  {(token.label or '—')[:28]:<28} "
                    f"{', '.join(token.scopes)[:28]:<28} {expiry:<26} "
                    f"{token.last_used_at or 'never'}"
                )

        _emit([token.as_dict() for token in tokens], as_json, render)
        return EXIT_OK

    return _run_admin(run)


def _cmd_token_rotate(args: argparse.Namespace) -> int:
    from app.scripts.cli_admin import EXIT_OK, resolve_actor, rotate_api_token

    def run() -> int:
        with _admin_session() as db:
            actor = resolve_actor(db, args.actor)
            raw_token, summary = rotate_api_token(
                db, actor, args.token_id, overlap_hours=args.overlap_hours
            )

        def render() -> None:
            print(f"rotated token {args.token_id} → {summary.id} ({summary.label})")
            if args.overlap_hours:
                print(
                    f"  the previous secret keeps working for up to {args.overlap_hours}h; "
                    "revoke it sooner with: cb token revoke "
                    f"{args.token_id}"
                )
            else:
                print("  the previous secret stopped working immediately")
            _print_token_secret(raw_token)

        _emit({**summary.as_dict(), "token": raw_token}, args.json, render)
        return EXIT_OK

    return _run_admin(run)


def _cmd_token_revoke(args: argparse.Namespace) -> int:
    from app.scripts.cli_admin import EXIT_OK, resolve_actor, revoke_api_token

    def run() -> int:
        with _admin_session() as db:
            actor = resolve_actor(db, args.actor)
            summary = revoke_api_token(db, actor, args.token_id)
        print(f"revoked token {summary.id} ({summary.label or '—'})")
        return EXIT_OK

    return _run_admin(run)


def _read_password_from_stdin() -> str:
    """A password read from stdin, never from argv.

    ``ps``, the shell history and any process listing see argv; they do not see
    stdin.  A password that arrived on the command line has already leaked by
    the time this process could refuse it, which is why there is no
    ``--password`` flag to refuse.
    """
    password = sys.stdin.readline().rstrip("\n")
    if not password:
        raise SystemExit("--password-stdin was given but stdin was empty")
    return password


def _cmd_user_create(args: argparse.Namespace) -> int:
    from app.scripts.cli_admin import EXIT_OK, create_user, resolve_actor

    def run() -> int:
        password = _read_password_from_stdin() if args.password_stdin else None
        with _admin_session() as db:
            actor = resolve_actor(db, args.actor)
            summary, generated = create_user(
                db,
                actor,
                email=args.email,
                role=args.role,
                password=password,
                display_name=args.display_name,
            )

        def render() -> None:
            print(f"created user {summary.id} ({summary.email}, role {summary.role})")
            print("  the account must set a new password on first login")
            if generated:
                print(
                    "This password is shown once and is not recoverable — store it now.",
                    file=sys.stderr,
                )
                print(generated)

        _emit(
            {**summary.as_dict(), "generated_password": generated},
            args.json,
            render,
        )
        return EXIT_OK

    return _run_admin(run)


def _cmd_user_list(as_json: bool) -> int:
    from app.scripts.cli_admin import EXIT_OK, list_users

    def run() -> int:
        with _admin_session() as db:
            users = list_users(db)

        def render() -> None:
            print(f"{'ID':>4}  {'EMAIL':<36} {'ROLE':<8} {'STATE':<10} LAST LOGIN")
            for user in users:
                state = "active" if user.is_active else "disabled"
                print(
                    f"{user.id:>4}  {user.email[:36]:<36} {user.role:<8} {state:<10} "
                    f"{user.last_login or 'never'}"
                )

        _emit([user.as_dict() for user in users], as_json, render)
        return EXIT_OK

    return _run_admin(run)


def _cmd_user_set_role(args: argparse.Namespace) -> int:
    from app.scripts.cli_admin import EXIT_OK, resolve_actor, set_user_role

    def run() -> int:
        with _admin_session() as db:
            actor = resolve_actor(db, args.actor)
            summary = set_user_role(db, actor, args.email, args.role)
        print(f"{summary.email} is now {summary.role}")
        return EXIT_OK

    return _run_admin(run)


def _cmd_user_set_active(args: argparse.Namespace, active: bool) -> int:
    from app.scripts.cli_admin import EXIT_OK, resolve_actor, set_user_active

    def run() -> int:
        with _admin_session() as db:
            actor = resolve_actor(db, args.actor)
            summary = set_user_active(db, actor, args.email, active)
        print(f"{summary.email} is now {'active' if summary.is_active else 'disabled'}")
        return EXIT_OK

    return _run_admin(run)


def _cmd_agent_list(args: argparse.Namespace) -> int:
    from app.scripts.cli_admin import EXIT_OK, list_agents

    def run() -> int:
        with _admin_session() as db:
            agents = list_agents(db, args.status)

        def render() -> None:
            if not agents:
                print("no agents")
                return
            print(f"{'ID':>4}  {'NAME':<28} {'STATUS':<10} {'VERSION':<12} LAST SEEN")
            for agent in agents:
                name = agent.name or agent.hostname or "—"
                print(
                    f"{agent.id:>4}  {name[:28]:<28} {agent.status:<10} "
                    f"{(agent.agent_version or '—'):<12} {agent.last_seen_at or 'never'}"
                )

        _emit([agent.as_dict() for agent in agents], args.json, render)
        return EXIT_OK

    return _run_admin(run)


def _cmd_agent_approve(args: argparse.Namespace) -> int:
    from app.scripts.cli_admin import EXIT_OK, approve_agent, resolve_actor

    def run() -> int:
        with _admin_session() as db:
            actor = resolve_actor(db, args.actor)
            summary = approve_agent(db, actor, args.agent_id)
        print(f"agent {summary.id} ({summary.name or summary.hostname or '—'}) is now active")
        return EXIT_OK

    return _run_admin(run)


def _cmd_agent_revoke(args: argparse.Namespace) -> int:
    from app.scripts.cli_admin import EXIT_OK, resolve_actor, revoke_agent

    def run() -> int:
        with _admin_session() as db:
            actor = resolve_actor(db, args.actor)
            summary = revoke_agent(db, actor, args.agent_id, args.reason)
        print(f"agent {summary.id} ({summary.name or summary.hostname or '—'}) is revoked")
        return EXIT_OK

    return _run_admin(run)


def _add_actor_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--actor",
        default=None,
        metavar="EMAIL",
        help=(
            "The administrator to record the change against. Optional when the install "
            "has exactly one active administrator; required otherwise, because the audit "
            "entry and the owning row both name a real user."
        ),
    )


def _add_json_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON on stdout instead of a table.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cb", description="Circuit Breaker administration CLI")
    group = parser.add_subparsers(dest="group", required=True)
    config = group.add_parser("config", help="Configuration commands")
    config_actions = config.add_subparsers(dest="action", required=True)
    validate = config_actions.add_parser(
        "validate", help="Validate the effective configuration; exit non-zero if invalid"
    )
    validate.add_argument(
        "--config",
        dest="config_path",
        default=None,
        help=(
            "Path to config.toml. Defaults to the same search order the server uses: "
            "$CB_CONFIG, /etc/circuit-breaker/config.toml, "
            "~/.config/circuitbreaker/config.toml, ./config.toml"
        ),
    )
    validate.add_argument(
        "--set",
        dest="overrides",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help=(
            "Override one setting for this pass. Highest precedence: beats the "
            "environment, which beats config.toml. NAME is an environment variable "
            "(CB_PORT=9090) or the config.toml key that maps to one "
            "(server.port=9090). Repeatable."
        ),
    )
    validate.add_argument(
        "--database",
        dest="database",
        action="store_true",
        help=(
            "Also read the AppSettings database tier, and report the conflicts only it "
            "can see (a shadowed CB_JWT_SECRET, a vault key the server would reject as "
            "stale). Opens a database connection; every other pass is offline."
        ),
    )

    snapshot = group.add_parser("snapshot", help="Full-state backup snapshots")
    snapshot_actions = snapshot.add_subparsers(dest="action", required=True)
    create = snapshot_actions.add_parser(
        "create", help="Build a full-state snapshot and print its path"
    )
    create.add_argument(
        "--out",
        dest="out",
        default=None,
        help="Directory to write the snapshot into. Defaults to the configured BACKUP_DIR.",
    )
    verify = snapshot_actions.add_parser(
        "verify", help="Validate a snapshot archive; exit non-zero if it cannot be restored"
    )
    verify.add_argument("archive", help="Path to the snapshot .tar.gz")
    encrypt = snapshot_actions.add_parser(
        "encrypt",
        help="Encrypt a snapshot to one age recipient for storage off this host",
    )
    encrypt.add_argument("archive", help="Path to the snapshot .tar.gz")
    encrypt.add_argument(
        "--recipient",
        required=True,
        help=(
            "The operator's age X25519 public key (age1...). Only the public half "
            "belongs here; the identity that decrypts the result must stay with the "
            "operator, off the host the backup came from."
        ),
    )

    # ── migrate ──────────────────────────────────────────────────────────────
    migrate = group.add_parser("migrate", help="Database schema migrations")
    migrate_actions = migrate.add_subparsers(dest="action", required=True)
    migrate_status = migrate_actions.add_parser(
        "status",
        help="Report the database's revision against this build's; exit 3 when behind",
    )
    _add_json_argument(migrate_status)
    migrate_actions.add_parser(
        "upgrade",
        help=(
            "Apply pending migrations, taking the same advisory lock the server takes, "
            "so it is safe to run while the stack is starting"
        ),
    )

    # ── token ────────────────────────────────────────────────────────────────
    token = group.add_parser("token", help="Scoped API tokens and service accounts")
    token_actions = token.add_subparsers(dest="action", required=True)

    token_create = token_actions.add_parser("create", help="Mint a scoped API token")
    token_create.add_argument("--label", required=True, help="What this token is for.")
    token_create.add_argument(
        "--scopes",
        nargs="+",
        default=[],
        metavar="SCOPE",
        help="Scopes to grant, e.g. --scopes read:* write:telemetry.",
    )
    token_create.add_argument(
        "--preset",
        default=None,
        help="A named scope set instead of --scopes (read_only, telemetry_ingest, …).",
    )
    expiry = token_create.add_mutually_exclusive_group(required=True)
    expiry.add_argument(
        "--expires-in-days",
        type=int,
        default=None,
        metavar="N",
        help="Expire the token N days from now.",
    )
    expiry.add_argument(
        "--never-expires",
        action="store_true",
        help="Issue a token with no expiry. Required explicitly; there is no silent default.",
    )
    _add_actor_argument(token_create)
    _add_json_argument(token_create)

    token_list = token_actions.add_parser(
        "list", help="List tokens: label, scopes, expiry, last use. Never the secret."
    )
    _add_json_argument(token_list)

    token_rotate = token_actions.add_parser(
        "rotate", help="Issue a replacement secret for a token, keeping its scopes and expiry"
    )
    token_rotate.add_argument("token_id", type=int, help="The token id from `cb token list`.")
    token_rotate.add_argument(
        "--overlap-hours",
        type=int,
        default=0,
        metavar="N",
        help=(
            "Keep the previous secret working for N hours so holders can be updated "
            "first. Never past the token's own expiry. Default 0: immediate cutover."
        ),
    )
    _add_actor_argument(token_rotate)
    _add_json_argument(token_rotate)

    token_revoke = token_actions.add_parser("revoke", help="Revoke a token immediately")
    token_revoke.add_argument("token_id", type=int, help="The token id from `cb token list`.")
    _add_actor_argument(token_revoke)

    # ── user ─────────────────────────────────────────────────────────────────
    user = group.add_parser("user", help="Local user accounts")
    user_actions = user.add_subparsers(dest="action", required=True)

    user_list = user_actions.add_parser("list", help="List accounts and their roles")
    _add_json_argument(user_list)

    user_create = user_actions.add_parser("create", help="Create a local account")
    user_create.add_argument("--email", required=True)
    user_create.add_argument("--role", default="viewer", choices=("admin", "editor", "viewer"))
    user_create.add_argument("--display-name", default=None)
    user_create.add_argument(
        "--password-stdin",
        action="store_true",
        help=(
            "Read the password from the first line of stdin. Without it a password is "
            "generated and printed once. There is deliberately no --password flag: argv "
            "is visible to every process on the host."
        ),
    )
    _add_actor_argument(user_create)
    _add_json_argument(user_create)

    user_role = user_actions.add_parser("set-role", help="Change an account's role")
    user_role.add_argument("email")
    user_role.add_argument("role", choices=("admin", "editor", "viewer"))
    _add_actor_argument(user_role)

    user_disable = user_actions.add_parser(
        "disable", help="Deactivate an account and revoke its sessions"
    )
    user_disable.add_argument("email")
    _add_actor_argument(user_disable)

    user_enable = user_actions.add_parser("enable", help="Reactivate an account")
    user_enable.add_argument("email")
    _add_actor_argument(user_enable)

    # ── agent ────────────────────────────────────────────────────────────────
    agent = group.add_parser("agent", help="cb-agent fleet")
    agent_actions = agent.add_subparsers(dest="action", required=True)

    agent_list = agent_actions.add_parser("list", help="List enrolled agents")
    agent_list.add_argument(
        "--status",
        default=None,
        choices=("pending", "active", "revoked", "rejected"),
        help="Only agents in this state.",
    )
    _add_json_argument(agent_list)

    agent_approve = agent_actions.add_parser(
        "approve", help="Approve a pending enrolment with the default capability grants"
    )
    agent_approve.add_argument("agent_id", type=int)
    _add_actor_argument(agent_approve)

    agent_revoke = agent_actions.add_parser("revoke", help="Revoke an agent's enrolment")
    agent_revoke.add_argument("agent_id", type=int)
    agent_revoke.add_argument("--reason", default=None)
    _add_actor_argument(agent_revoke)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.group == "config" and args.action == "validate":
        return _cmd_config_validate(args.config_path, args.overrides, database=args.database)
    if args.group == "snapshot" and args.action == "create":
        return _cmd_snapshot_create(args.out)
    if args.group == "snapshot" and args.action == "verify":
        return _cmd_snapshot_verify(args.archive)
    if args.group == "snapshot" and args.action == "encrypt":
        return _cmd_snapshot_encrypt(args.archive, args.recipient)
    if args.group == "migrate":
        if args.action == "status":
            return _cmd_migrate_status(args.json)
        if args.action == "upgrade":
            return _cmd_migrate_upgrade()
    if args.group == "token":
        if args.action == "create":
            return _cmd_token_create(args)
        if args.action == "list":
            return _cmd_token_list(args.json)
        if args.action == "rotate":
            return _cmd_token_rotate(args)
        if args.action == "revoke":
            return _cmd_token_revoke(args)
    if args.group == "user":
        if args.action == "list":
            return _cmd_user_list(args.json)
        if args.action == "create":
            return _cmd_user_create(args)
        if args.action == "set-role":
            return _cmd_user_set_role(args)
        if args.action == "disable":
            return _cmd_user_set_active(args, active=False)
        if args.action == "enable":
            return _cmd_user_set_active(args, active=True)
    if args.group == "agent":
        if args.action == "list":
            return _cmd_agent_list(args)
        if args.action == "approve":
            return _cmd_agent_approve(args)
        if args.action == "revoke":
            return _cmd_agent_revoke(args)
    # argparse's required subparsers make this unreachable in practice; keep it
    # so a future top-level command cannot silently fall through to exit 0.
    parser.error(f"unknown command: {args.group} {args.action}")


if __name__ == "__main__":
    sys.exit(main())
