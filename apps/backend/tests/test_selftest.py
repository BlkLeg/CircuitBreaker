"""--selftest must fail for the reason v0.4.2 failed, and pass otherwise.

v0.4.2 shipped a frozen binary with no `app.main` in it. Every release gate was
green, because the only execution any of them performed was `--version`, which
start.py resolves from an embedded file and returns on before the application
is ever imported.

So both directions are asserted here. A self-test that only ever passes is the
gate that let v0.4.2 through, wearing a different name.
"""

from __future__ import annotations

import pytest

from app.startup.selftest import SelfTestResult, format_result, run_selftest


def test_selftest_passes_on_a_correct_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CB_DB_URL", "postgresql://fake:fake@localhost/fake")
    result = run_selftest()
    assert result.ok, f"self-test failed on a correct tree: {result.failure}"
    assert result.failure is None
    assert "app.main" in result.checked
    assert "app.workers.discovery" in result.checked


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
