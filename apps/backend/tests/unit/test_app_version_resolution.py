"""GOV-09 / ACC-17: an installed artifact must be able to say which version it is.

`circuit-breaker --version` printed "unknown" from the installed .deb, which is
what the installed-artifact smoke gate caught. resolve_app_version() knew two
layouts — a VERSION file beside the executable, and one in the source tree — and
a packaged install is neither: nfpm puts the binary in <prefix>/bin and the
share tree in <prefix>/share/circuit-breaker.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.core.config import _version_candidates, resolve_app_version


@pytest.fixture(autouse=True)
def _no_ambient_version(monkeypatch):
    """Neither override may decide the outcome of these tests."""
    monkeypatch.delenv("APP_VERSION", raising=False)
    monkeypatch.delenv("CB_SHARE_DIR", raising=False)


def test_packaged_layout_version_is_found(monkeypatch, tmp_path):
    """The deb/rpm/apk layout: <prefix>/bin/circuit-breaker + <prefix>/share/circuit-breaker/."""
    prefix = tmp_path / "usr" / "local"
    (prefix / "bin").mkdir(parents=True)
    share = prefix / "share" / "circuit-breaker"
    share.mkdir(parents=True)
    (share / "VERSION").write_text("9.9.9-packaged\n", encoding="utf-8")

    monkeypatch.setattr(sys, "executable", str(prefix / "bin" / "circuit-breaker"))

    assert resolve_app_version() == "9.9.9-packaged"


def test_bundle_layout_version_is_still_found(monkeypatch, tmp_path):
    """The tarball/AppImage layout — the binary sits next to its own share/."""
    bundle = tmp_path / "bundle"
    (bundle / "share").mkdir(parents=True)
    (bundle / "share" / "VERSION").write_text("9.9.9-bundle\n", encoding="utf-8")

    monkeypatch.setattr(sys, "executable", str(bundle / "circuit-breaker"))

    assert resolve_app_version() == "9.9.9-bundle"


def test_frozen_bundle_version_is_found(monkeypatch, tmp_path):
    """PyInstaller ships VERSION inside the binary, so it travels with it.

    build_native_release.py passes --add-data for REPO_ROOT/VERSION; this is the
    candidate that reads it back out of the unpacked bundle.
    """
    meipass = tmp_path / "_MEI123"
    meipass.mkdir()
    (meipass / "VERSION").write_text("9.9.9-frozen\n", encoding="utf-8")

    # An executable path that matches no other candidate, so only _MEIPASS can answer.
    monkeypatch.setattr(sys, "executable", str(tmp_path / "nowhere" / "circuit-breaker"))
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)

    assert resolve_app_version() == "9.9.9-frozen"


def test_share_dir_env_still_wins(monkeypatch, tmp_path):
    """CB_SHARE_DIR is the operator override and must outrank every derived path."""
    override = tmp_path / "override"
    override.mkdir()
    (override / "VERSION").write_text("9.9.9-override\n", encoding="utf-8")

    packaged = tmp_path / "usr" / "local" / "share" / "circuit-breaker"
    packaged.mkdir(parents=True)
    (packaged / "VERSION").write_text("9.9.9-packaged\n", encoding="utf-8")

    monkeypatch.setenv("CB_SHARE_DIR", str(override))
    monkeypatch.setattr(
        sys, "executable", str(tmp_path / "usr" / "local" / "bin" / "circuit-breaker")
    )

    assert resolve_app_version() == "9.9.9-override"


def test_packaged_candidate_is_derived_from_the_executable_prefix(monkeypatch):
    """Pin the exact path, because it has to match nfpm.yaml's install targets."""
    monkeypatch.setattr(sys, "executable", "/usr/local/bin/circuit-breaker")

    assert Path("/usr/local/share/circuit-breaker/VERSION") in _version_candidates()
