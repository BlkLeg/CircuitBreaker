"""GOV-20: a release candidate must never move a stable channel.

Loaded via importlib rather than `import scripts.release_channel` to match the
convention already used by test_security_suppressions.py — `scripts/` is a
directory of entrypoints, not an importable package.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts/release_channel.py"
_SPEC = importlib.util.spec_from_file_location("release_channel", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

is_prerelease = _MODULE.is_prerelease
channel_tags = _MODULE.channel_tags


@pytest.mark.parametrize(
    "version,expected",
    [
        ("1.0.0", False),
        ("1.0.1", False),
        ("2.3.4", False),
        ("1.0.0-rc.1", True),
        ("1.0.0-rc.2", True),
        ("1.0.0-alpha.1", True),
        ("1.0.0-beta", True),
        ("1.0.0-dev", True),
        ("dev-abc1234", True),
    ],
)
def test_is_prerelease(version: str, expected: bool) -> None:
    assert is_prerelease(version) is expected


def test_stable_version_gets_latest_tag() -> None:
    assert channel_tags("1.0.0") == ["1.0.0", "latest"]


def test_prerelease_never_gets_latest_tag() -> None:
    assert channel_tags("1.0.0-rc.2") == ["1.0.0-rc.2"]
    assert "latest" not in channel_tags("1.0.0-rc.2")


def test_rejects_empty_version() -> None:
    with pytest.raises(SystemExit):
        channel_tags("")


def test_cli_emits_shell_consumable_fields() -> None:
    out = subprocess.run(
        [sys.executable, str(_SCRIPT), "--version", "1.0.0-rc.2", "--field", "prerelease"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert out.stdout.strip() == "true"

    out = subprocess.run(
        [sys.executable, str(_SCRIPT), "--version", "1.0.0", "--field", "tags"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert out.stdout.split() == ["1.0.0", "latest"]
