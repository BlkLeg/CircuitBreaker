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
