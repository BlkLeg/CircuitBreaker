"""An unreadable config directory must not crash the service at startup.

This is the defect the packaged boot gate found on its first real execution.
`configure_runtime` probed its default config path with a bare
`Path(...).exists()`, and `Path.exists()` is not total: it answers False for a
missing file but *raises* when the filesystem refuses to answer. A
`/etc/circuit-breaker` the service account cannot traverse therefore produced:

    PermissionError: [Errno 13] Permission denied:
      '/etc/circuit-breaker/config.yaml'
    [PYI-3850:ERROR] Failed to execute script 'start'

and the unit crash-looped with no diagnosis. The packaged layout has no
`config.yaml` at all — it uses `config.toml` — so the probe was asking about a
file that is *expected* to be absent, and the answer to "I cannot tell" was a
traceback.

The distinction that matters, and that this file pins, is between a path the
operator asked for and the built-in default. Continuing without a config the
operator named would run with settings they believe are applied; continuing
without one nobody asked for is the normal packaged case.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pytest

from app.start import _native_config_path


def _args(config: str | None) -> argparse.Namespace:
    return argparse.Namespace(config=config)


# The interpreter matters here, which is part of why this survived.
#
# CPython 3.12 — the version the release binary is frozen from
# (.github/workflows/build.yml pins actions/setup-python to 3.12) — lets EACCES
# out of `Path.exists()`: `_ignore_error` swallows only ENOENT, ENOTDIR, EBADF
# and ELOOP. CPython 3.14, which a developer machine is as likely to be running,
# returns False for it instead. So the crash is real in the artifact and
# invisible on a laptop, and a test built on real filesystem permissions would
# pass locally for the wrong reason.
#
# Raising from `Path.exists()` directly is therefore not a shortcut around the
# filesystem — it is the only way to assert the shipped interpreter's behaviour
# on any interpreter. The permission error is the one 3.12 produces.
_EACCES = PermissionError(13, "Permission denied")


@pytest.fixture()
def exists_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(self: Path, *args: object, **kwargs: object) -> bool:
        raise _EACCES

    monkeypatch.setattr(Path, "exists", _raise)


def test_an_unreadable_default_path_warns_and_continues(
    exists_denied: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Nobody asked for this file, so its unreadability is not fatal."""
    monkeypatch.delenv("CB_CONFIG_PATH", raising=False)
    monkeypatch.setattr(sys, "argv", ["circuit-breaker"])

    result = _native_config_path(_args("/etc/circuit-breaker/config.yaml"))

    assert result is None
    stderr = capsys.readouterr().err
    assert "cannot determine whether the default config exists" in stderr
    assert "Permission denied" in stderr
    assert "/etc/circuit-breaker/config.yaml" in stderr


def test_an_unreadable_requested_path_refuses_to_start(
    exists_denied: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A config the operator named must not be silently skipped.

    Starting anyway would run with settings the operator believes are applied
    and are not, which is the silent-fallback shape this project refuses.
    """
    monkeypatch.setenv("CB_CONFIG_PATH", "/srv/cb/config.yaml")
    monkeypatch.setattr(sys, "argv", ["circuit-breaker"])

    with pytest.raises(SystemExit) as excinfo:
        _native_config_path(_args("/srv/cb/config.yaml"))

    message = str(excinfo.value)
    assert "cannot read the requested config file" in message
    assert "--config or CB_CONFIG_PATH" in message


def test_an_explicit_config_flag_also_refuses(
    exists_denied: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--config` on the command line counts as asking for it."""
    monkeypatch.delenv("CB_CONFIG_PATH", raising=False)
    monkeypatch.setattr(sys, "argv", ["circuit-breaker", "--config", "/srv/cb/config.yaml"])

    with pytest.raises(SystemExit):
        _native_config_path(_args("/srv/cb/config.yaml"))


def test_a_missing_file_is_simply_absent(tmp_path: Path) -> None:
    """The packaged norm: no config.yaml, no config, no complaint."""
    assert _native_config_path(_args(str(tmp_path / "config.yaml"))) is None


def test_a_readable_file_is_returned(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("host: 127.0.0.1\n", encoding="utf-8")

    assert _native_config_path(_args(str(config))) == str(config)


def test_no_path_at_all_is_none() -> None:
    assert _native_config_path(_args(None)) is None


def test_configure_runtime_actually_uses_the_guarded_probe(
    exists_denied: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The wiring, not just the helper.

    Every test above calls `_native_config_path` directly, so all of them stay
    green if `configure_runtime` goes back to probing with a bare
    `Path(...).exists()` — which is precisely the line that crash-looped the
    packaged service. Mutation-tested: restoring that expression fails this
    test and only this test.
    """
    from app.start import build_parser, configure_runtime

    monkeypatch.delenv("CB_CONFIG_PATH", raising=False)
    monkeypatch.setenv("CB_DB_URL", "postgresql://fake:fake@localhost/fake")
    monkeypatch.setattr(sys, "argv", ["circuit-breaker"])

    runtime = configure_runtime(build_parser().parse_args([]))

    assert runtime["host"]
    assert "cannot determine whether the default config exists" in capsys.readouterr().err
