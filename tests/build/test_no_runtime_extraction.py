"""The application no longer extracts itself at run time, and nothing may reintroduce that.

AGT-11 existed to contain PyInstaller --onefile's $TMPDIR/_MEI<random>
extraction. With the python-build-standalone tree there is nothing to extract,
so the reaping ExecStartPre lines are gone — and this test is what stops a
future unit from quietly needing them again. TMPDIR stays per-unit: that is
ordinary hygiene, not a PyInstaller accommodation.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NATIVE_UNITS = [ROOT / "deploy" / "systemd" / n for n in ("circuitbreaker-backend.service", "circuitbreaker-worker@.service")]
PACKAGE_UNITS = sorted((ROOT / "packaging").glob("circuit-breaker*.service"))
NFPM = ROOT / "nfpm.yaml"
BUILD_SCRIPT = ROOT / "scripts" / "build_native_release.py"


@pytest.mark.parametrize("unit", NATIVE_UNITS + PACKAGE_UNITS, ids=lambda p: p.name)
def test_no_unit_reaps_or_mentions_extraction_dirs(unit: Path) -> None:
    text = unit.read_text(encoding="utf-8")
    assert "_MEI" not in text, f"{unit.name} still references PyInstaller extraction directories"


@pytest.mark.parametrize("unit", NATIVE_UNITS, ids=lambda p: p.name)
def test_native_units_keep_a_private_tmpdir_and_no_private_tmp(unit: Path) -> None:
    text = unit.read_text(encoding="utf-8")
    assert 'Environment="TMPDIR=/var/lib/circuitbreaker/run/%N"' in text
    assert "PrivateTmp=true" not in text, "discovery reads the host's /tmp lease files by absolute path"
    assert "ExecStart=/opt/circuitbreaker/bin/circuit-breaker" in text


def test_default_packaging_is_the_tree() -> None:
    text = BUILD_SCRIPT.read_text(encoding="utf-8")
    match = re.search(r'"--packaging",\s*choices=\[[^\]]*\],\s*default="([a-z]+)"', text)
    assert match and match.group(1) == "pbs", "the release build must default to the hermetic tree"


def test_packages_ship_the_interpreter_and_symlink_the_binary() -> None:
    text = NFPM.read_text(encoding="utf-8")
    assert "dist/native/bundle/python/" in text and "dst: /opt/circuitbreaker/python/" in text
    assert re.search(r"src: /opt/circuitbreaker/bin/circuit-breaker\s*\n\s*dst: /usr/local/bin/circuit-breaker\s*\n\s*type: symlink", text)
    assert "dist/native/bundle/circuit-breaker\n" not in text, "no onefile binary is packaged any more"
