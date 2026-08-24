"""AGT-11: the PyInstaller --onefile bundle must extract somewhere we own.

--onefile extracts the whole application into $TMPDIR/_MEI<random> on every
start and only removes it on a clean exit. A crash loop, a reboot mid-start, or
a failed upgrade therefore leaves full copies behind with nothing reaping them.

On a native install SIX units run that same bundle as user `breaker`
(backend + five workers), all into the shared /tmp, and the backend restarts
on failure. Each unit is given its own extraction directory under the app's
data dir and reaps only that directory, because a shared reap directory would
let a starting worker delete the backend's live extraction.

PrivateTmp= is deliberately NOT the fix here: discovery reads the host's real
/tmp/dnsmasq.leases and /tmp/dhcp.leases (services/discovery_dhcp.py:59,
services/discovery_service.py:107), which a private /tmp namespace hides.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
UNIT_DIR = ROOT / "deploy" / "systemd"

# The native units whose ExecStart is the PyInstaller onefile bundle.
BUNDLE_UNITS = ["circuitbreaker-backend.service", "circuitbreaker-worker@.service"]

EXTRACTION_ROOT = "/var/lib/circuitbreaker/run"


def _unit(name: str) -> str:
    return (UNIT_DIR / name).read_text()


@pytest.mark.parametrize("name", BUNDLE_UNITS)
def test_unit_runs_the_onefile_bundle(name: str) -> None:
    """Guard the premise: if ExecStart stops being the bundle, this file is moot."""
    assert "/opt/circuitbreaker/bin/circuit-breaker" in _unit(name)


@pytest.mark.parametrize("name", BUNDLE_UNITS)
def test_unit_points_tmpdir_at_an_owned_directory(name: str) -> None:
    text = _unit(name)
    assert f'Environment="TMPDIR={EXTRACTION_ROOT}/%N"' in text, (
        f"{name} must set TMPDIR to a per-unit directory under {EXTRACTION_ROOT}"
    )


@pytest.mark.parametrize("name", BUNDLE_UNITS)
def test_unit_reaps_only_its_own_stale_extractions(name: str) -> None:
    text = _unit(name)
    reaps = re.findall(r"rm -rf [^\n']*_MEI\*", text)
    assert reaps, f"{name} must reap stale _MEI* at start"
    for reap in reaps:
        # Strip shell quoting so `"…/run/%N"/_MEI*` compares as a plain path.
        normalized = reap.replace('"', "")
        assert f"{EXTRACTION_ROOT}/%N/" in normalized, (
            f"{name} reaps outside its own directory, which could delete another "
            f"unit's live extraction: {reap!r}"
        )


@pytest.mark.parametrize("name", BUNDLE_UNITS)
def test_unit_never_sweeps_the_shared_tmp(name: str) -> None:
    """A bare /tmp/_MEI* sweep could delete another application's live bundle."""
    text = _unit(name)
    assert "rm -rf /tmp/_MEI" not in text
    assert not re.search(r"rm -rf\s+/tmp/\*", text)


@pytest.mark.parametrize("name", BUNDLE_UNITS)
def test_unit_does_not_enable_private_tmp(name: str) -> None:
    """PrivateTmp would hide the host lease files discovery probes by absolute path."""
    assert "PrivateTmp=true" not in _unit(name)


def test_extraction_root_lives_under_the_native_data_dir() -> None:
    """setup.sh creates /var/lib/circuitbreaker owned breaker:breaker, so the
    unit's ExecStartPre can create a subdirectory as its own unprivileged user."""
    assert EXTRACTION_ROOT.startswith("/var/lib/circuitbreaker/")
