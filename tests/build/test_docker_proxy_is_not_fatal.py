"""The Docker socket proxy must not be able to kill the backend.

wait-for-services.sh runs as ExecStartPre for circuitbreaker-backend.service.
Every probe in it gates startup, and for pgbouncer, Redis, NATS and the
database that is correct — the application cannot serve a request without any
of them.

The Docker socket proxy is not in that class. It feeds container telemetry,
which is opt-in on top of the core product; the installer itself treats a
failed Docker install as a warning and carries on. It nevertheless used to
`exit 1` on timeout, so an optional feature could take the whole application
down at ExecStartPre.

That is exactly what happened in v0.4.2. The proxy unit was installed with the
placeholder ${CB_DOCKER_BIN} unrendered, systemd could not exec it (203/EXEC),
the proxy restart-looped, this script burned its full 60s and failed — and the
operator was shown "Backend failed to start / Check: journalctl -u
circuitbreaker-backend", three services away from the defect, with the install
aborted at the last phase.

These tests run the real block out of the shipped script against a stubbed
curl, because "warns instead of exiting" is a property of the code path, not of
its text.
"""

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy" / "scripts" / "wait-for-services.sh"

_MARKER = "# Docker socket proxy"


def _docker_proxy_block() -> str:
    """The proxy section of the shipped script, from its comment to the end."""
    text = SCRIPT.read_text(encoding="utf-8")
    index = text.find(_MARKER)
    assert index != -1, f"{SCRIPT} no longer contains a section marked '{_MARKER}'"
    block = text[index:]
    assert "DOCKER_PROXY_ENABLED" in block, "the proxy section no longer gates on DOCKER_PROXY_ENABLED"
    return block


def _run(tmp_path: Path, curl_exit: int) -> subprocess.CompletedProcess[str]:
    """Run the block with a curl stub, so no probe ever touches the network."""
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    curl = stub_dir / "curl"
    curl.write_text(f"#!/bin/sh\nexit {curl_exit}\n", encoding="utf-8")
    curl.chmod(0o755)

    script = textwrap.dedent(
        """
        set -euo pipefail
        MAX_WAIT=2
        INTERVAL=1
        DOCKER_PROXY_ENABLED=true
        """
    ) + _docker_proxy_block()

    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        timeout=60,
        env={"PATH": f"{stub_dir}:/usr/bin:/bin", "LC_ALL": "C"},
    )


def test_an_unreachable_proxy_warns_and_lets_the_backend_start(tmp_path):
    result = _run(tmp_path, curl_exit=1)

    assert result.returncode == 0, (
        "wait-for-services.sh exited non-zero because the Docker socket proxy was "
        "unreachable. It runs as ExecStartPre, so this stops circuitbreaker-backend "
        "from starting at all over an opt-in telemetry feature.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "WARNING" in result.stderr, "an operator must still be told the proxy is down"
    assert "circuitbreaker-docker-proxy" in result.stderr, (
        "the warning must name the unit to look at, or it cannot be acted on"
    )
    assert "FATAL" not in result.stderr, "the proxy being down is not fatal any more"


def test_a_reachable_proxy_is_reported_ready(tmp_path):
    """The happy path still has to work, and still has to say so."""
    result = _run(tmp_path, curl_exit=0)

    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "Docker proxy ready" in result.stdout
    assert "WARNING" not in result.stderr


def test_the_required_dependencies_are_still_fatal():
    """The point is that the *optional* probe stopped exiting — not that probes
    stopped exiting. pgbouncer, Redis, NATS and the database still gate startup."""
    text = SCRIPT.read_text(encoding="utf-8")
    required = text[: text.find(_MARKER)]

    missing = [
        name
        for name, needle in (
            ("pgbouncer/wait_port", "did not start within"),
            ("Redis", "Redis did not accept authenticated connections within"),
            ("NATS JetStream", "NATS JetStream did not become ready within"),
            ("database via pgbouncer", "Cannot connect to DB through pgbouncer within"),
        )
        if needle not in required
    ]
    assert not missing, (
        "these required-dependency probes lost their timeout failure: " + ", ".join(missing)
    )
    assert required.count("exit 1") >= 4, (
        "the backend must still refuse to start without pgbouncer, Redis, NATS and "
        "the database — only the Docker socket proxy is allowed to degrade"
    )
