"""The mono smoke has one definition: scripts/ci/tier2-mono-smoke.sh."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ci" / "tier2-mono-smoke.sh"


def _text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_the_script_requires_exactly_one_image_argument():
    for argv in ([], ["a", "b"]):
        result = subprocess.run(["bash", str(SCRIPT), *argv], capture_output=True, text=True,
                                cwd=REPO_ROOT, env={"PATH": "/usr/bin:/bin"})
        assert result.returncode == 2, result.stderr
        assert "image" in result.stderr.lower()


def test_every_dev_ci_assertion_moved_into_the_script():
    """Each probe the build-docker job ran must still run, by its distinctive command."""
    text = _text()
    for needle in (
        "/api/v1/livez", "grep -q '\"alive\"'", "/api/v1/readyz",
        "http://127.0.0.1:${CB_SMOKE_PORT}/", "301",
        "https://127.0.0.1:${CB_SMOKE_PORT_HTTPS}/", '<div id="root"',
        "supervisorctl -c /etc/supervisor/conf.d/supervisord.conf status",
        "for proc in postgres nats redis backend-api nginx",
        "{{.RestartCount}}", "stop -t 30",
    ):
        assert needle in text, f"tier2-mono-smoke.sh lost the assertion containing {needle!r}"


def test_the_secrets_never_outlive_the_script():
    text = _text()
    assert "trap" in text and "EXIT" in text, "no EXIT trap: a failed assertion would leave .env behind"
    assert "shred" in text
    assert "umask 077" in text
    assert "::add-mask::" in text


def test_umask_is_scoped_to_the_env_write():
    """umask must not leak past the .env write and change file-creation
    permissions for artifacts/diagnostics or anything written afterwards."""
    text = _text()
    assert "( umask 077" in text or "(\n    umask 077" in text, (
        "umask 077 must run inside a subshell scoped to the .env write, not "
        "at script scope"
    )


def test_teardown_never_prompts_for_a_password():
    """sudo must never block a CI run (or a developer's terminal) on a
    password prompt; -n makes a missing/expired credential a normal failure
    instead of a hang."""
    assert "sudo -n rm -rf" in _text()


def test_refuses_to_start_against_a_developer_workspace():
    """A pre-existing .env or an already-running circuitbreaker container
    must stop the script before it installs the EXIT trap — see the
    stub-driven behavior tests in test_tier2_mono_smoke_behavior.py for the
    runtime proof."""
    text = _text()
    assert "refuse_if_unsafe_to_start" in text
    assert "-e .env" in text
    assert "docker ps" in text
    assert text.index("refuse_if_unsafe_to_start\n") < text.index("trap on_exit EXIT"), (
        "the refuse-to-start check must run before the EXIT trap is installed"
    )


def test_running_stack_probe_asks_the_engine_not_compose():
    """docker-compose.yml's ${VAR:?...} guards (CB_DB_PASSWORD, CB_VAULT_KEY,
    CB_JWT_SECRET, NATS_AUTH_TOKEN) make Compose interpolate and fail the
    whole file for every subcommand while no .env exists yet -- exactly the
    moment this guard runs. `docker compose ... ps -q` would then print
    nothing and exit non-zero, and `[ -n "$(...)" ]` reads that empty output
    as "nothing running": fails open on the one case the guard exists for.
    So the probe must ask the Docker engine directly for the pinned
    container name, never through `docker compose`."""
    text = _text()
    assert "docker compose -f docker-compose.yml ps -q" not in text
    assert "docker ps -a --filter" in text
    assert "name=^circuitbreaker$" in text
    # Fail closed: a `docker ps` that itself errors (e.g. daemon
    # unreachable) must refuse to start rather than read as "nothing
    # running".
    assert 'if ! running="$(docker ps' in text


def test_diagnostics_strip_secrets_from_the_inspect_capture():
    """Config.Env holds the four smoke secrets in clear; ::add-mask:: masks
    log output only, not an uploaded artifact, so the inspect capture must
    drop Env before writing the file. See the stub test for runtime proof
    that a secret embedded in Config.Env does not survive into the file."""
    text = _text()
    assert 'pop("Env"' in text
    assert "docker inspect circuitbreaker" in text


def test_retry_loops_use_an_overridable_sleep_with_the_old_default():
    """A test harness without a real container needs to drive the retry
    loops without paying five seconds per attempt; CI must keep today's
    cadence, so the default has to stay 5."""
    text = _text()
    assert "CB_SMOKE_SLEEP:-5" in text
    assert "sleep 5" not in text, "a literal sleep 5 is no longer overridable by CB_SMOKE_SLEEP"
