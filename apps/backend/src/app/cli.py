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
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import socket
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.startup_validation import (
    allow_degraded_dependencies,
    validate_core_dependencies,
    validate_secret_value,
)
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
    # Not settings the gates read, but they decide which files the tiers above
    # are read from, so an operator debugging a surprising verdict needs them.
    "CB_CONFIG",
    "CB_DATA_DIR",
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


def resolve_config(
    env: Mapping[str, str], *, config_path: str | Path | None = None
) -> ResolvedConfig:
    """Merge every configuration tier this process can read, in the server's order.

    Environment first, then config.toml, then — for the vault key alone —
    ``$CB_DATA_DIR/.env``.  The database tier is out of reach offline; see the
    module docstring.
    """
    values = {name: str(value) for name, value in env.items()}
    sources = {name: "environment" for name in _KNOWN_SETTINGS if name in values}
    errors: list[str] = []

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

    return ResolvedConfig(values=values, sources=sources, errors=tuple(errors))


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
    config: ResolvedConfig | Mapping[str, str], *, config_path: str | Path | None = None
) -> ConfigReport:
    """Validate a configuration against the same rules the server enforces at startup.

    Accepts either a raw mapping (typically ``os.environ``), which is resolved
    across the tiers first, or an already-resolved configuration.
    """
    resolved = (
        config
        if isinstance(config, ResolvedConfig)
        else resolve_config(config, config_path=config_path)
    )
    env = resolved.values
    report = ConfigReport(sources=dict(resolved.sources))
    for file_error in resolved.errors:
        report.error(file_error)

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


def _cmd_config_validate(config_path: str | None = None) -> int:
    resolved = resolve_config(os.environ, config_path=config_path)
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


def _cmd_snapshot_verify(archive: str) -> int:
    try:
        manifest = verify_archive(Path(archive), installed_version=os.environ.get("CB_VERSION"))
    except SnapshotProblem as problem:
        print(str(problem), file=sys.stderr)
        return 1

    print(json.dumps(manifest, indent=2))
    return 0


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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.group == "config" and args.action == "validate":
        return _cmd_config_validate(args.config_path)
    if args.group == "snapshot" and args.action == "create":
        return _cmd_snapshot_create(args.out)
    if args.group == "snapshot" and args.action == "verify":
        return _cmd_snapshot_verify(args.archive)
    # argparse's required subparsers make this unreachable in practice; keep it
    # so a future top-level command cannot silently fall through to exit 0.
    parser.error(f"unknown command: {args.group} {args.action}")


if __name__ == "__main__":
    sys.exit(main())
