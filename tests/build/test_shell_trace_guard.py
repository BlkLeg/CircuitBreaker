"""`bash -x` on the installer or cb wrote every secret into the trace.

A support session's `bash -x install.sh ... 2> trace.log` held the vault key,
the JWT secret and the database, Redis and NATS credentials: setup.sh sources
/etc/circuitbreaker/.env and passes passwords on command lines. Each script
that handles those values now switches tracing off unless CB_ALLOW_XTRACE=1.
"""
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ("install.sh", "deploy/setup.sh", "cb", "deploy/cli/cb")
START = "if [[ $- == *x* && \"${CB_ALLOW_XTRACE:-}\" != 1 ]]; then"


def _guard(rel: str) -> str:
    text = (ROOT / rel).read_text()
    assert text.count(START) == 1, f"{rel} no longer has exactly one trace guard"
    begin = text.index(START)
    return text[begin:text.index("fi\n", begin) + 3]


def _run(rel: str, allow: bool) -> subprocess.CompletedProcess[str]:
    script = _guard(rel) + 'case $- in *x*) echo TRACING ;; *) echo QUIET ;; esac\nTRACED_LATER=marker-after-the-guard\n'
    env = {"PATH": "/usr/bin:/bin"}
    if allow:
        env["CB_ALLOW_XTRACE"] = "1"
    return subprocess.run(["bash", "-x", "-c", script], capture_output=True, text=True, check=False, env=env)


@pytest.mark.parametrize("rel", SCRIPTS)
def test_tracing_is_switched_off_before_secrets_are_handled(rel: str) -> None:
    r = _run(rel, allow=False)
    assert r.stdout.strip() == "QUIET"
    assert "marker-after-the-guard" not in r.stderr
    assert "Shell tracing (bash -x) is off" in r.stderr


@pytest.mark.parametrize("rel", SCRIPTS)
def test_tracing_stays_on_when_asked_for_by_name(rel: str) -> None:
    r = _run(rel, allow=True)
    assert r.stdout.strip() == "TRACING"
    assert "marker-after-the-guard" in r.stderr


def test_the_guard_precedes_every_env_read() -> None:
    for rel in SCRIPTS:
        text = (ROOT / rel).read_text()
        guard = text.index(START)
        if rel == "install.sh":
            # install.sh reads no secret before main(); the guard is its first statement.
            assert text.index("main() {\n") < guard < text.index("main() {\n") + 1200
        else:
            first_env = text.index("source /etc/circuitbreaker/.env")
            assert guard < first_env, f"{rel} sources .env before its trace guard"
