"""SRV-05: `cb config validate` must detect invalid combinations offline.

Offline matters twice over.  The point is to catch a bad config before the
service tries to start with it, so a pass must open no socket at all — not to
Redis, NATS or Postgres, and not to a name server either, because an
air-gapped host is exactly where this command earns its keep and a resolver
timeout there would fail a good proxy.  `test_validation_opens_no_socket` pins
that property; the claim went unguarded once and drifted.

The other half is that the validator must judge the same configuration the
server boots with: config.toml under the environment (BLOCKING-1), the vault
key's $CB_DATA_DIR/.env tier, and — for the tiers that live in the database and
cannot be read from here — a warning that names them rather than a verdict that
guesses (BLOCKING-4).

Which is why the vault keys in this file are real Fernet keys and not 48 filler
characters: vault_service accepts a key at no tier unless Fernet does, and a key
it rejects is dropped without an error, so a fixture that is merely long enough
would be testing a configuration the server would never actually run on.
"""

from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app.cli import OverrideError, parse_overrides, resolve_config, validate_config

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BACKEND_SRC = Path(__file__).resolve().parents[1] / "src"

# Generated rather than hard-coded: a literal would have to be kept valid by
# hand, and Fernet.generate_key() is the same call an operator is told to make.
_VAULT_KEY = Fernet.generate_key().decode()
_OTHER_VAULT_KEY = Fernet.generate_key().decode()

# 48 characters, so it clears the 32-character minimum and is not a placeholder
# — everything the shared secret rules check — but not base64-decodable to 32
# bytes, so Fernet refuses it and vault_service drops it.
_NON_FERNET_KEY = "not-a-fernet-key-but-long-enough-to-pass-length!"


@pytest.fixture(autouse=True)
def _pin_file_tiers(monkeypatch, tmp_path):
    """Point the file tiers at empty per-test locations.

    Both config.toml discovery and the vault key's .env tier search absolute
    paths (/etc/circuit-breaker/config.toml, ~/.config/..., ./data/.env), so
    without this a real installation on the machine running the suite could
    change a verdict.  CB_CONFIG is the first candidate the search tries, and
    an empty TOML file contributes nothing.
    """
    empty_config = tmp_path / "empty-config.toml"
    empty_config.write_text("")
    data_dir = tmp_path / "empty-data"
    data_dir.mkdir()
    monkeypatch.setenv("CB_CONFIG", str(empty_config))
    monkeypatch.setenv("CB_DATA_DIR", str(data_dir))


def _valid_env() -> dict[str, str]:
    return {
        "CB_CONFIG": os.environ["CB_CONFIG"],
        "CB_DATA_DIR": os.environ["CB_DATA_DIR"],
        "CB_JWT_SECRET": "j" * 48,
        "CB_VAULT_KEY": _VAULT_KEY,
        "CB_REDIS_URL": "redis://127.0.0.1:6379/0",
        "CB_ALLOW_DIRECT_EGRESS": "true",
    }


def _subprocess_env(**overrides: str) -> dict[str, str]:
    """A minimal environment that can still import `app`, and nothing more.

    No HOME, no DATABASE_URL, no virtualenv activation — PYTHONPATH is the only
    concession, because `python -m app.cli` has to find the package at all.
    CB_CONFIG/CB_DATA_DIR carry the fixture's empty file tiers through, for the
    same reason the fixture sets them.
    """
    return {
        "PATH": "/usr/bin:/bin",
        "PYTHONPATH": str(_BACKEND_SRC),
        "CB_CONFIG": os.environ["CB_CONFIG"],
        "CB_DATA_DIR": os.environ["CB_DATA_DIR"],
        **overrides,
    }


def test_valid_configuration_reports_ok():
    report = validate_config(_valid_env())
    assert report.ok, report.errors
    assert report.errors == []


def test_missing_jwt_secret_is_a_warning_that_names_the_database():
    """BLOCKING-4: CB_JWT_SECRET is the *fallback*, not the primary source.

    app/core/users.py::_get_jwt_secret reads AppSettings.jwt_secret from the
    database first and only falls back to the environment, and
    settings_service.get_or_create_settings generates one there when the row has
    none — so packaging/postinstall.sh, which writes no CB_JWT_SECRET into the
    env file, produces a *correct* native install.  Reporting a hard error for
    that would train operators to ignore the validator.  The database cannot be
    read offline, so the honest verdict is a warning naming the tier that was
    not consulted.
    """
    env = _valid_env()
    del env["CB_JWT_SECRET"]
    report = validate_config(env)
    assert report.ok, report.errors
    assert any("AppSettings.jwt_secret" in warning for warning in report.warnings)


def test_placeholder_secret_is_an_error():
    """A secret that is *present* and bad is an error: no later tier is consulted."""
    env = _valid_env()
    env["CB_JWT_SECRET"] = "change_me"
    report = validate_config(env)
    assert not report.ok
    assert any("placeholder" in e for e in report.errors)


def test_short_secret_is_an_error():
    env = _valid_env()
    env["CB_JWT_SECRET"] = "tooshort"
    report = validate_config(env)
    assert not report.ok
    assert any("too short" in e for e in report.errors)


def test_secret_rules_match_the_startup_gate():
    """The CLI applies validate_startup_secrets' rules per secret; pin them equal.

    cli.py cannot call validate_startup_secrets() itself — it checks both
    secrets in one call, and each secret needs a different verdict when it is
    absent — so it calls that module's per-secret primitive with its own copy of
    the label and minimum length.  This fails if either copy drifts.
    """
    from app.core.startup_validation import validate_startup_secrets

    short = "x" * 8
    report = validate_config({**_valid_env(), "CB_JWT_SECRET": short, "CB_VAULT_KEY": short})
    gate_errors = validate_startup_secrets(jwt_secret=short, vault_key=short)
    assert gate_errors
    for message in gate_errors:
        assert message in report.errors


def test_memory_rate_limit_storage_is_an_error():
    """SEC-13: rate limits must use shared storage, not per-process memory."""
    env = _valid_env()
    env["CB_RATE_LIMIT_STORAGE_URL"] = "memory://"
    env["CB_REDIS_URL"] = ""
    report = validate_config(env)
    assert not report.ok
    assert any("shared" in e.lower() or "memory" in e.lower() for e in report.errors)


def test_missing_egress_policy_is_an_error():
    env = _valid_env()
    del env["CB_ALLOW_DIRECT_EGRESS"]
    report = validate_config(env)
    assert not report.ok
    assert any("EGRESS" in e.upper() for e in report.errors)


def test_report_never_echoes_a_secret_value():
    """Diagnostics must redact secrets (SRV-05)."""
    env = _valid_env()
    env["CB_JWT_SECRET"] = "supersecretvalue" + "x" * 32
    report = validate_config(env)
    blob = "\n".join(report.errors + report.warnings + list(report.sources.values()))
    assert "supersecretvalue" not in blob


def test_sources_record_where_each_setting_came_from():
    report = validate_config(_valid_env())
    assert report.sources["CB_JWT_SECRET"] == "environment"


def test_validation_restores_the_process_environment():
    """A pass binds os.environ to the mapping under test; it must put it back."""
    before = dict(os.environ)
    validate_config({"CB_JWT_SECRET": "change_me"})
    assert dict(os.environ) == before


# --------------------------------------------------------------------------
# BLOCKING-1: config.toml is part of the configuration being validated
# --------------------------------------------------------------------------


def test_config_toml_supplies_a_setting_and_records_the_source(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(f'[security]\nvault_key = "{_VAULT_KEY}"\n')
    env = _valid_env()
    del env["CB_VAULT_KEY"]
    env["CB_CONFIG"] = str(config)

    resolved = resolve_config(env)
    assert resolved.values["CB_VAULT_KEY"] == _VAULT_KEY
    assert resolved.sources["CB_VAULT_KEY"] == f"config.toml ({config})"
    assert validate_config(env).ok


def test_environment_wins_over_config_toml(tmp_path):
    """start.py's loader only fills names the environment has not already set."""
    config = tmp_path / "config.toml"
    config.write_text('[security]\nvault_key = "change_me"\n')
    env = _valid_env()
    env["CB_CONFIG"] = str(config)

    report = validate_config(env)
    assert report.ok, report.errors
    assert report.sources["CB_VAULT_KEY"] == "environment"


def test_cb_config_is_searched_before_the_working_directory(tmp_path, monkeypatch):
    """The CLI's file search must pick the same file load_config_toml() picks."""
    chosen = tmp_path / "chosen.toml"
    chosen.write_text(f'[security]\nvault_key = "{_OTHER_VAULT_KEY}"\n')
    workdir = tmp_path / "cwd"
    workdir.mkdir()
    (workdir / "config.toml").write_text('[security]\nvault_key = "change_me"\n')
    monkeypatch.chdir(workdir)

    env = _valid_env()
    del env["CB_VAULT_KEY"]
    env["CB_CONFIG"] = str(chosen)
    assert resolve_config(env).sources["CB_VAULT_KEY"] == f"config.toml ({chosen})"

    # And the loader the server actually boots with agrees.
    from app.core.config_toml import load_config_toml

    monkeypatch.setenv("CB_CONFIG", str(chosen))
    monkeypatch.delenv("CB_VAULT_KEY", raising=False)
    load_config_toml()
    assert os.environ["CB_VAULT_KEY"] == _OTHER_VAULT_KEY


def test_unreadable_config_toml_is_an_error(tmp_path):
    """start.py swallows a parse failure; a validator must not."""
    config = tmp_path / "config.toml"
    config.write_text("[security\nvault_key = ")
    env = _valid_env()
    env["CB_CONFIG"] = str(config)

    report = validate_config(env)
    assert not report.ok
    assert any("config.toml" in e for e in report.errors)


def test_cli_exits_nonzero_on_a_bad_value_that_only_config_toml_supplies(tmp_path):
    """BLOCKING-1 end to end: the file the server reads decides the exit code."""
    config = tmp_path / "config.toml"
    config.write_text('[security]\nvault_key = "change_me"\n\n[redis]\nurl = "memory://"\n')
    env = _valid_env()
    del env["CB_VAULT_KEY"]
    del env["CB_REDIS_URL"]
    env["CB_CONFIG"] = str(config)

    result = subprocess.run(
        [sys.executable, "-m", "app.cli", "config", "validate"],
        capture_output=True,
        text=True,
        env=_subprocess_env(**env),
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 1, combined
    assert "placeholder" in combined
    assert f"config.toml ({config})" in result.stdout


def test_cli_config_flag_selects_the_file(tmp_path):
    config = tmp_path / "elsewhere.toml"
    config.write_text('[security]\nvault_key = "change_me"\n')
    env = _valid_env()
    del env["CB_VAULT_KEY"]

    result = subprocess.run(
        [sys.executable, "-m", "app.cli", "config", "validate", "--config", str(config)],
        capture_output=True,
        text=True,
        env=_subprocess_env(**env),
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 1, combined
    assert "placeholder" in combined


# --------------------------------------------------------------------------
# BLOCKING-4: the vault key's file tier, and the database tier neither has
# --------------------------------------------------------------------------


def test_vault_key_is_read_from_the_data_env_file(tmp_path):
    """vault_service resolves env -> $CB_DATA_DIR/.env -> AppSettings."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / ".env").write_text(f"CB_VAULT_KEY={_VAULT_KEY}\n")
    env = _valid_env()
    del env["CB_VAULT_KEY"]
    env["CB_DATA_DIR"] = str(data_dir)

    report = validate_config(env)
    assert report.ok, report.errors
    assert report.sources["CB_VAULT_KEY"] == str(data_dir / ".env")
    assert not any("CB_VAULT_KEY is unset" in w for w in report.warnings)


def test_missing_vault_key_warns_and_names_the_remaining_tier():
    env = _valid_env()
    del env["CB_VAULT_KEY"]
    report = validate_config(env)
    assert report.ok, report.errors
    assert any("CB_VAULT_KEY is unset" in w and "AppSettings" in w for w in report.warnings)


def test_a_bad_vault_key_in_the_data_env_file_is_an_error(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / ".env").write_text("CB_VAULT_KEY=change_me\n")
    env = _valid_env()
    del env["CB_VAULT_KEY"]
    env["CB_DATA_DIR"] = str(data_dir)

    report = validate_config(env)
    assert not report.ok
    assert any("placeholder" in e for e in report.errors)


# --------------------------------------------------------------------------
# The vault key has a format rule the shared secret rules do not know about
# --------------------------------------------------------------------------


def test_a_long_non_fernet_vault_key_is_an_error():
    """The whole defect: long enough and not a placeholder is not good enough.

    validate_secret_value() passes _NON_FERNET_KEY — 48 characters, no
    placeholder word.  vault_service.load_vault_key() rejects it at the
    environment tier and falls through *without raising*, so main.py's Phase-7
    gate only ever validates whatever later tier answered, and the operator's
    key is discarded in silence.  A validator that says "configuration valid"
    here is describing a configuration the server does not run.
    """
    from app.core.startup_validation import validate_secret_value

    assert validate_secret_value("Vault encryption key", _NON_FERNET_KEY, min_length=32) is None

    report = validate_config({**_valid_env(), "CB_VAULT_KEY": _NON_FERNET_KEY})
    assert not report.ok, "a key the vault service will discard must not validate"
    assert any("Fernet" in e for e in report.errors), report.errors
    # And it names the tier the discarded key came from, because the fix is to
    # replace *that* value, not whichever one the server ended up booting on.
    assert any("environment" in e for e in report.errors), report.errors


def test_a_real_fernet_key_passes():
    report = validate_config({**_valid_env(), "CB_VAULT_KEY": Fernet.generate_key().decode()})
    assert report.ok, report.errors


def test_a_non_fernet_vault_key_in_the_data_env_file_is_an_error(tmp_path):
    """The rule is per tier, because load_vault_key() applies it at every tier."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / ".env").write_text(f"CB_VAULT_KEY={_NON_FERNET_KEY}\n")
    env = _valid_env()
    del env["CB_VAULT_KEY"]
    env["CB_DATA_DIR"] = str(data_dir)

    report = validate_config(env)
    assert not report.ok
    assert any("Fernet" in e and str(data_dir / ".env") in e for e in report.errors), report.errors


def test_the_vault_key_rule_is_the_vault_services_own_predicate(monkeypatch):
    """Pin reuse, not agreement: a second copy of the rule would drift.

    vault_service._is_valid_fernet_key is what every tier of load_vault_key()
    consults.  Forcing it to reject a genuinely valid key must change the
    validator's verdict; if it does not, cli.py has grown its own copy of the
    base64/32-byte rule and will keep passing keys the loader has started to
    refuse.
    """
    from app.services import vault_service

    monkeypatch.setattr(vault_service, "_is_valid_fernet_key", lambda key: False)
    report = validate_config(_valid_env())
    assert not report.ok
    assert any("Fernet" in e for e in report.errors), report.errors


def test_the_vault_key_report_still_redacts_the_bad_key():
    """An error about a secret's format must not quote the secret."""
    report = validate_config({**_valid_env(), "CB_VAULT_KEY": _NON_FERNET_KEY})
    blob = "\n".join(report.errors + report.warnings + list(report.sources.values()))
    assert _NON_FERNET_KEY not in blob


def test_cli_exits_nonzero_on_a_non_fernet_vault_key():
    result = subprocess.run(
        [sys.executable, "-m", "app.cli", "config", "validate"],
        capture_output=True,
        text=True,
        env=_subprocess_env(**{**_valid_env(), "CB_VAULT_KEY": _NON_FERNET_KEY}),
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 1, combined
    assert "Fernet" in combined
    assert _NON_FERNET_KEY not in combined


def test_the_jwt_secret_has_no_format_rule_the_validator_could_miss():
    """The other half of the finding: CB_JWT_SECRET has no downstream format gate.

    The vault key's problem is that a consumer (Fernet) refuses values the
    validator accepts.  The JWT secret's only consumer is HS256, which takes any
    non-empty byte string — core.security.create_token/decode_token round-trip
    the same 48-character non-base64 value that Fernet rejects — so length and
    the placeholder screen really are the whole rule, and there is nothing here
    for the validator to be missing.  If a key-format requirement (a JWK, an
    asymmetric algorithm) is ever introduced, this test fails and the validator
    needs the same treatment the vault key just got.
    """
    from app.core.security import create_token, decode_token

    token = create_token(7, _NON_FERNET_KEY, 1)
    assert decode_token(token, _NON_FERNET_KEY) == 7

    assert validate_config({**_valid_env(), "CB_JWT_SECRET": _NON_FERNET_KEY}).ok


# --------------------------------------------------------------------------
# MINOR-3: the pass opens no socket, including no DNS query
# --------------------------------------------------------------------------


def test_validation_opens_no_socket(monkeypatch):
    """An air-gapped host must get a verdict, not a resolver timeout.

    CB_EGRESS_PROXY_URL reaches validate_outbound_url()'s SSRF screen, which
    resolves the hostname.  cli.py refuses resolution for the duration of a
    pass and reports the deferral; if that guard is removed these stubs fire.
    """

    def _forbidden(*args, **kwargs):
        raise AssertionError("offline validation must not touch the network")

    monkeypatch.setattr(socket, "getaddrinfo", _forbidden)
    monkeypatch.setattr(socket, "create_connection", _forbidden)
    monkeypatch.setattr(socket.socket, "connect", _forbidden)

    env = _valid_env()
    del env["CB_ALLOW_DIRECT_EGRESS"]
    env["CB_EGRESS_PROXY_URL"] = "http://proxy.invalid:3128"

    report = validate_config(env)
    assert report.ok, report.errors
    assert any("proxy.invalid" in w for w in report.warnings)
    # The guard restores what it replaced rather than leaking a stub.
    assert socket.getaddrinfo is _forbidden


def test_a_syntactically_invalid_proxy_is_still_an_error():
    """Deferring DNS must not defer the checks that never needed it."""
    env = _valid_env()
    del env["CB_ALLOW_DIRECT_EGRESS"]
    env["CB_EGRESS_PROXY_URL"] = "ftp://proxy.invalid:3128"

    report = validate_config(env)
    assert not report.ok
    assert any("CB_EGRESS_PROXY_URL is invalid" in e for e in report.errors)


def test_cli_never_prints_a_secret_value():
    secret = "supersecretvalue" + "x" * 32
    result = subprocess.run(
        [sys.executable, "-m", "app.cli", "config", "validate"],
        capture_output=True,
        text=True,
        env=_subprocess_env(**{**_valid_env(), "CB_JWT_SECRET": secret}),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert secret not in (result.stdout + result.stderr)


def test_cli_exits_zero_on_valid_config():
    result = subprocess.run(
        [sys.executable, "-m", "app.cli", "config", "validate"],
        capture_output=True,
        text=True,
        env=_subprocess_env(**_valid_env()),
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_cli_exits_nonzero_on_invalid_config():
    result = subprocess.run(
        [sys.executable, "-m", "app.cli", "config", "validate"],
        capture_output=True,
        text=True,
        env=_subprocess_env(CB_JWT_SECRET="change_me"),
    )
    assert result.returncode == 1
    assert "placeholder" in (result.stdout + result.stderr)


def _packaged_entrypoint() -> Path:
    """Resolve BACKEND_ENTRYPOINT out of the release script's source text.

    The script is not importable from the backend test package (pythonpath is
    apps/backend/src), and importing it only to read one constant would drag in
    the whole build tooling, so the assignment is parsed instead.
    """
    build_script = _REPO_ROOT / "scripts" / "build_native_release.py"
    match = re.search(r"^BACKEND_ENTRYPOINT\s*=\s*(.+)$", build_script.read_text(), re.MULTILINE)
    assert match, "scripts/build_native_release.py no longer defines BACKEND_ENTRYPOINT"
    parts = re.findall(r'"([^"]+)"', match.group(1))
    assert parts, f"could not read a path out of: {match.group(1)}"
    return _REPO_ROOT.joinpath(*parts)


def test_entrypoint_supports_config_validate_flag():
    """cb config validate on native/binary installs shells to this flag."""
    entrypoint = _packaged_entrypoint()
    source = entrypoint.read_text()
    assert "--config-validate" in source, "packaged entrypoint must expose --config-validate"
    assert "app.cli" in source or "validate_config" in source


def test_entrypoint_config_validate_runs_without_a_database():
    """The flag must be handled before anything binds a port or opens a socket."""
    result = subprocess.run(
        [sys.executable, str(_packaged_entrypoint()), "--config-validate"],
        capture_output=True,
        text=True,
        env=_subprocess_env(CB_JWT_SECRET="change_me"),
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "placeholder" in (result.stdout + result.stderr)
    assert "DATABASE_URL" not in result.stderr


def test_entrypoint_forwards_an_explicit_toml_path(tmp_path):
    """--config <file>.toml must reach the validator, not just the server."""
    config = tmp_path / "config.toml"
    config.write_text('[security]\nvault_key = "change_me"\n')
    env = _valid_env()
    del env["CB_VAULT_KEY"]
    # An empty CB_CONFIG file would otherwise win the search; the flag must beat it.
    result = subprocess.run(
        [
            sys.executable,
            str(_packaged_entrypoint()),
            "--config",
            str(config),
            "--config-validate",
        ],
        capture_output=True,
        text=True,
        env=_subprocess_env(**env),
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 1, combined
    assert "placeholder" in combined


# --------------------------------------------------------------------------
# SRV-05: the command-line tier
#
# "One precedence order across file, environment, database, and CLI" needs
# four tiers, and the CLI tier used to be `--config <file>` alone — which
# selects *which file tier* is read rather than supplying a value, so the
# order the requirement names had three levels in it, not four.
# --------------------------------------------------------------------------


def test_a_command_line_override_beats_the_environment():
    env = _valid_env()
    env["CB_REDIS_URL"] = "redis://from-the-environment:6379/0"
    report = validate_config(
        resolve_config(env, overrides={"CB_REDIS_URL": "redis://from-the-flag:6379/0"})
    )
    assert report.sources["CB_REDIS_URL"] == "command line (--set)"
    assert report.ok, report.errors


def test_a_command_line_override_beats_config_toml(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text('[redis]\nurl = "redis://from-the-file:6379/0"\n')
    env = _valid_env()
    del env["CB_REDIS_URL"]

    resolved = resolve_config(
        env, config_path=config, overrides={"CB_REDIS_URL": "redis://from-the-flag:6379/0"}
    )
    assert resolved.values["CB_REDIS_URL"] == "redis://from-the-flag:6379/0"
    assert resolved.sources["CB_REDIS_URL"] == "command line (--set)"


def test_an_override_may_be_written_as_the_config_toml_key():
    """`--set server.port=9090` and `--set CB_PORT=9090` must mean the same thing.

    The operator has the TOML key in front of them; making them translate it to
    an environment variable name to test a change is the kind of friction that
    ends in the change being made in the file and validated nowhere.
    """
    assert parse_overrides(["server.port=9090"]) == {"CB_PORT": "9090"}
    assert parse_overrides(["CB_PORT=9090"]) == {"CB_PORT": "9090"}


def test_an_override_naming_a_key_the_server_does_not_read_is_refused():
    with pytest.raises(OverrideError) as excinfo:
        parse_overrides(["server.prot=9090"])
    assert "server.prot" in str(excinfo.value)


def test_an_override_that_is_not_an_assignment_is_refused():
    with pytest.raises(OverrideError):
        parse_overrides(["CB_PORT"])


def test_cli_reports_a_bad_override_as_usage_not_as_an_invalid_config():
    result = subprocess.run(
        [sys.executable, "-m", "app.cli", "config", "validate", "--set", "nope.nope=1"],
        capture_output=True,
        text=True,
        env=_subprocess_env(**_valid_env()),
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert "nope.nope" in result.stderr


def test_cli_applies_an_override_end_to_end():
    """The flag must reach the same merge the report is built from."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.cli",
            "config",
            "validate",
            "--set",
            "CB_RATE_LIMIT_STORAGE_URL=memory://",
        ],
        capture_output=True,
        text=True,
        env=_subprocess_env(**_valid_env()),
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Rate-limit storage" in (result.stdout + result.stderr)


# --------------------------------------------------------------------------
# SRV-05: a value's shape is part of "valid"
#
# The gap the ledger recorded: `cb config validate` checked required settings
# and invalid combinations but not value types, so a config.toml carrying
# `port = "not-a-port"` was reported valid — CB_PORT is copied out of the file
# and never parsed by anything the validator called.
# --------------------------------------------------------------------------


def test_a_non_numeric_port_in_config_toml_is_an_error(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text('[server]\nport = "not-a-port"\n')
    env = _valid_env()

    report = validate_config(resolve_config(env, config_path=config))
    assert not report.ok
    assert any("CB_PORT" in error and "not-a-port" in error for error in report.errors)


def test_a_port_outside_the_tcp_range_is_an_error():
    report = validate_config({**_valid_env(), "CB_PORT": "70000"})
    assert not report.ok
    assert any("65535" in error for error in report.errors)


def test_a_flag_the_env_reader_would_silently_ignore_is_an_error():
    """`CB_ALLOW_DIRECT_EGRESS=on` is the failure this rule exists for.

    `_env_flag` accepts 1/true/yes and nothing else, so `on` — which is what
    anyone arriving from nginx or systemd writes — is read as *off*, with no
    error and no log line, and the egress gate the operator thought they had
    waived refuses to start the server.
    """
    report = validate_config({**_valid_env(), "CB_ALLOW_DIRECT_EGRESS": "on"})
    assert not report.ok
    assert any("silently treated as OFF" in error for error in report.errors)


def test_a_boolean_pydantic_would_reject_is_reported_not_raised():
    """Settings() is built inside the pass and raises on a value it cannot parse.

    Before the value rules ran first, `CB_UPDATE_CHECK=maybe` came out of
    `validate_config` as a pydantic ValidationError — a traceback on the
    operator's terminal from the one command whose entire job is to turn a bad
    configuration into a sentence.
    """
    report = validate_config({**_valid_env(), "CB_UPDATE_CHECK": "maybe"})
    assert not report.ok
    assert any("CB_UPDATE_CHECK" in error and "boolean" in error for error in report.errors)


def test_a_malformed_trusted_proxy_cidr_is_an_error():
    report = validate_config({**_valid_env(), "CB_TRUSTED_PROXY_CIDRS": "10.0.0.0/8,10.0.0.0/64"})
    assert not report.ok
    assert any("10.0.0.0/64" in error for error in report.errors)


def test_a_database_url_that_is_not_postgres_is_an_error():
    report = validate_config({**_valid_env(), "CB_DB_URL": "sqlite:///./cb.db"})
    assert not report.ok
    assert any("postgresql://" in error for error in report.errors)


def test_a_value_error_stops_the_gates_and_says_so():
    """The gates read these settings; running them on a value nothing can parse
    produces either a second, confusing error or a traceback."""
    report = validate_config({**_valid_env(), "CB_PORT": "not-a-port"})
    assert not report.ok
    assert any("dependency gates were not run" in warning for warning in report.warnings)


def test_every_value_rule_names_a_setting_the_report_can_locate():
    """A value error is only actionable once the report says which tier set it.

    "CB_PORT is not a number" is no help to an operator with a config.toml in
    three places, so a setting with a rule must also be one whose source is
    reported.
    """
    from app.cli import _KNOWN_SETTINGS
    from app.scripts.config_values import VALUE_RULES

    assert not set(VALUE_RULES) - set(_KNOWN_SETTINGS)


def test_a_valid_configuration_with_typed_settings_still_passes():
    env = {
        **_valid_env(),
        "CB_PORT": "8080",
        "CB_UPDATE_CHECK": "false",
        "CB_TRUSTED_PROXY_CIDRS": "127.0.0.1/32,::1/128",
        "CORS_ORIGINS": "https://cb.example.com",
        "DB_POOL_SIZE": "10",
    }
    report = validate_config(env)
    assert report.ok, report.errors


# --------------------------------------------------------------------------
# SRV-05: the database tier
#
# Opt-in, because the offline default is what makes the command usable on a
# host whose database is down.  What the tier is for is not the two values it
# supplies but the two conflicts nothing else can see: a CB_JWT_SECRET the
# database shadows, and a CB_VAULT_KEY vault_service would discard as stale.
# --------------------------------------------------------------------------


@pytest.fixture
def committed_app_settings(app_cfg):
    """Write app_settings fields on a committed connection, and put them back.

    `resolve_config(database=True)` opens its own engine on purpose — it must
    read the database the configuration under test names, not the one this
    process happens to be bound to — so it cannot see anything held in the
    test's SAVEPOINT.
    """
    from app.db.models import AppSettings
    from app.db.session import SessionLocal

    saved: dict[str, object] = {}

    def apply(**fields: object) -> None:
        with SessionLocal() as session:
            cfg = session.get(AppSettings, 1)
            for name, value in fields.items():
                saved.setdefault(name, getattr(cfg, name))
                setattr(cfg, name, value)
            session.commit()

    yield apply

    if saved:
        with SessionLocal() as session:
            cfg = session.get(AppSettings, 1)
            for name, value in saved.items():
                setattr(cfg, name, value)
            session.commit()


def _database_env(**overrides: str) -> dict[str, str]:
    env = _valid_env()
    env["CB_DB_URL"] = os.environ["CB_DB_URL"]
    env.update(overrides)
    return env


def test_the_database_tier_supplies_the_jwt_secret_and_names_itself(committed_app_settings):
    committed_app_settings(jwt_secret="d" * 48)
    env = _database_env()
    del env["CB_JWT_SECRET"]

    resolved = resolve_config(env, database=True)
    assert resolved.sources["CB_JWT_SECRET"] == "database (app_settings.jwt_secret)"
    report = validate_config(resolved)
    assert report.ok, report.errors


def test_the_database_tier_reports_a_jwt_secret_the_environment_cannot_win(
    committed_app_settings,
):
    """app.core.users reads AppSettings.jwt_secret first, so the env value signs nothing."""
    committed_app_settings(jwt_secret="d" * 48)
    report = validate_config(resolve_config(_database_env(CB_JWT_SECRET="e" * 48), database=True))
    assert any("signs nothing" in warning for warning in report.warnings)


def test_a_vault_key_the_server_would_discard_as_stale_is_an_error(committed_app_settings):
    """load_vault_key() cross-checks the environment key against vault_key_hash.

    A key that fails it is dropped without an error — the server falls through
    to the next tier — so the operator's configured key decrypts nothing and
    nothing anywhere says so.
    """
    import hashlib

    committed_app_settings(
        vault_key_hash=hashlib.sha256(_OTHER_VAULT_KEY.encode()).hexdigest(),
    )
    report = validate_config(resolve_config(_database_env(), database=True))
    assert not report.ok
    assert any("vault_key_hash" in error for error in report.errors)


def test_a_vault_key_that_matches_the_stored_hash_passes(committed_app_settings):
    import hashlib

    committed_app_settings(vault_key_hash=hashlib.sha256(_VAULT_KEY.encode()).hexdigest())
    report = validate_config(resolve_config(_database_env(), database=True))
    assert report.ok, report.errors


def test_the_database_tier_reports_an_unreachable_database_without_its_password():
    """Asked for and unavailable is an error; the report stays pasteable."""
    env = _valid_env()
    env["CB_DB_URL"] = "postgresql://breaker:hunter2@127.0.0.1:1/circuitbreaker"

    report = validate_config(resolve_config(env, database=True))
    assert not report.ok
    blob = "\n".join(report.errors)
    assert "--database" in blob
    assert "hunter2" not in blob


def test_the_database_tier_is_off_unless_it_is_asked_for(monkeypatch):
    """Everything above is opt-in: the default pass still opens no socket."""

    def _forbidden(*args, **kwargs):
        raise AssertionError("the default pass must not touch the network")

    monkeypatch.setattr(socket, "getaddrinfo", _forbidden)
    monkeypatch.setattr(socket, "create_connection", _forbidden)
    monkeypatch.setattr(socket.socket, "connect", _forbidden)

    report = validate_config(resolve_config(_database_env()))
    assert report.ok, report.errors
