"""--selftest must fail for the reason v0.4.2 failed, and pass otherwise.

v0.4.2 shipped a frozen binary with no `app.main` in it. Every release gate was
green, because the only execution any of them performed was `--version`, which
start.py resolves from an embedded file and returns on before the application
is ever imported.

So both directions are asserted here. A self-test that only ever passes is the
gate that let v0.4.2 through, wearing a different name.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.startup.selftest import SelfTestResult, format_result, run_selftest


def test_selftest_passes_on_a_correct_tree(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CB_DB_URL", "postgresql://fake:fake@localhost/fake")
    monkeypatch.chdir(tmp_path)
    result = run_selftest()
    assert result.ok, f"self-test failed on a correct tree: {result.failure}"
    assert result.failure is None
    assert "app.main" in result.checked
    assert "app.workers.discovery" in result.checked
    # See test_import_purity.py for the subprocess-level version of this
    # invariant, which conftest's temp-directory redirection cannot mask.
    assert not list(tmp_path.iterdir()), "resolving self-test targets wrote to the cwd"


def test_selftest_fails_when_the_asgi_module_is_unimportable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact v0.4.2 shape: the application is not in the bundle."""
    monkeypatch.setattr("app.startup.selftest.ASGI_TARGET", "app.definitely_not_here:app")
    result = run_selftest()
    assert not result.ok
    assert result.failure is not None
    assert "app.definitely_not_here" in result.failure


def test_selftest_fails_when_a_worker_module_is_unimportable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.startup import selftest as selftest_module

    monkeypatch.setattr(
        selftest_module,
        "WORKER_MODULES",
        {**selftest_module.WORKER_MODULES, "phantom": "app.workers.phantom_worker"},
    )
    result = run_selftest()
    assert not result.ok
    assert result.failure is not None
    assert "app.workers.phantom_worker" in result.failure


def test_selftest_fails_when_the_asgi_attribute_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Importing the module is not enough — uvicorn does a getattr too."""
    monkeypatch.setattr("app.startup.selftest.ASGI_TARGET", "app.main:no_such_attribute")
    result = run_selftest()
    assert not result.ok
    assert result.failure is not None
    assert "no_such_attribute" in result.failure


def test_format_result_is_one_line_and_names_the_counts() -> None:
    result = SelfTestResult(ok=True, checked=["app.main", "app.workers.discovery"], failure=None)
    line = format_result(result)
    assert "\n" not in line
    assert "2" in line


def test_cli_selftest_exits_zero_and_prints_one_line(capsys: pytest.CaptureFixture[str]) -> None:
    from app.start import main

    code = main(["--selftest"])
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.strip().startswith("selftest OK")
    assert captured.out.strip().count("\n") == 0


def test_cli_selftest_exits_one_and_reports_to_stderr(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("app.startup.selftest.ASGI_TARGET", "app.definitely_not_here:app")
    from app.start import main

    code = main(["--selftest"])
    captured = capsys.readouterr()
    assert code == 1
    assert "selftest FAILED" in captured.err
    assert "app.definitely_not_here" in captured.err


def test_cli_selftest_runs_before_config_is_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    """--selftest must not need a config file, a database URL or a data dir.

    It runs inside a build container and on a freshly installed host before any
    of those exist. If configure_runtime is reached, the flag is wired too late.
    """

    def _explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("configure_runtime must not run under --selftest")

    monkeypatch.setattr("app.start.configure_runtime", _explode)
    from app.start import main

    assert main(["--selftest"]) == 0


# ── Failure detail ───────────────────────────────────────────────────────────
#
# The installer journey caught `--selftest` failing as an unprivileged user
# with, in full:
#
#     selftest FAILED — could not import ASGI module 'app.main':
#     PermissionError(13, 'Permission denied')
#
# An errno-only exception names no file, because the error came from a syscall
# rather than an open. There was nothing to act on, from the one module in the
# codebase whose entire job is to be acted on — `cb doctor` and `cb diag
# bundle` both surface exactly this string to an operator.


def test_an_import_failure_carries_its_traceback(monkeypatch: pytest.MonkeyPatch) -> None:
    """The summary line is unchanged; the traceback follows it."""
    import app.startup.selftest as selftest_module

    def _raise(_name: str) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(selftest_module.importlib, "import_module", _raise)
    result = selftest_module.run_selftest()

    assert not result.ok
    assert result.detail, "an import failure must carry a traceback"
    assert "PermissionError" in result.detail
    assert "Traceback" in result.detail

    rendered = selftest_module.format_result(result)
    assert rendered.splitlines()[0].startswith("selftest FAILED — "), (
        "the first line must stay the one-line summary; callers log it alone"
    )
    assert "Traceback" in rendered, "the traceback must reach the operator"


def test_a_successful_selftest_stays_one_line() -> None:
    """The traceback must not turn a healthy result into a wall of text."""
    from app.startup.selftest import format_result, run_selftest

    result = run_selftest()
    assert result.ok, result.failure
    assert result.detail is None
    assert "\n" not in format_result(result)


# ── Dynamic-import package probes (gh#104) ──────────────────────────────────
#
# `scripts/build_native_release.py` hidden-imports `proxmoxer` and
# `apscheduler` with `collect_submodules` because both pick part of
# themselves via a runtime string, invisible to PyInstaller's static import
# graph. `collect_submodules` puts the files in the bundle; it does not prove
# they import. gh#104 was exactly that: proxmoxer.backends was silently
# dropped and every Proxmox VE integration died on connect, with no gate
# ever having imported it.


def test_selftest_probes_every_dynamic_import_package_on_a_correct_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CB_DB_URL", "postgresql://fake:fake@localhost/fake")
    result = run_selftest()
    assert result.ok, result.failure
    from app.startup.selftest import DYNAMIC_IMPORT_PROBES

    for probe_module in DYNAMIC_IMPORT_PROBES.values():
        assert probe_module in result.checked


def test_selftest_fails_when_a_dynamic_import_probe_is_unimportable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.startup.selftest as selftest_module

    monkeypatch.setattr(
        selftest_module,
        "DYNAMIC_IMPORT_PROBES",
        {**selftest_module.DYNAMIC_IMPORT_PROBES, "phantom_pkg": "phantom_pkg.no_such_submodule"},
    )
    result = selftest_module.run_selftest()
    assert not result.ok
    assert result.failure is not None
    assert "phantom_pkg.no_such_submodule" in result.failure


def test_a_malformed_target_has_no_traceback_to_offer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Not every failure is an exception; that path must not invent a detail."""
    import app.startup.selftest as selftest_module

    monkeypatch.setattr(selftest_module, "ASGI_TARGET", "no-colon-here")
    result = selftest_module.run_selftest()

    assert not result.ok
    assert result.detail is None
    assert "\n" not in selftest_module.format_result(result)
