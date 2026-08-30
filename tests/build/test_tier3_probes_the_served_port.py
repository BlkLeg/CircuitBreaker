"""The tier has to probe the port the package actually serves.

Found by the first execution of `fedora-rpm-amd64` that got far enough to reach
the check. `tier3-artifact.sh` hardcoded `http://127.0.0.1:8000`, which is the
*dev* port -- what `make dev` binds and what the Vite proxy forwards to
(docs/installation/docker-compose-source.md). The packaged service takes its
default from `start.py`, which is 8080, and the package's own closing text tells
the operator to open `http://localhost:8080`.

The consequence is worth recording: the row had never once reached a live
service. Phase 2's F1 (`CB_DATA_DIR`) crashed the service before startup
completed, so the probe never got as far as connecting to the wrong port, and
the defect sat latent behind a louder one. "The row ran and found a bug" is not
the same claim as "the row ran green", and only the second one backs a tier.

A literal in the tier and a literal in start.py are two copies of one fact, which
is the shape of defect this file exists to prevent. The test couples them.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TIER3 = REPO_ROOT / "scripts/ci/tier3-artifact.sh"
START = REPO_ROOT / "apps/backend/src/app/start.py"
POSTINSTALL = REPO_ROOT / "packaging/postinstall.sh"


def _packaged_default_port() -> int:
    """The port start.py falls back to when nothing overrides it."""
    match = re.search(r'_get_option\(\s*args\.port,\s*"PORT",\s*config,\s*"port",\s*(\d+)', START.read_text("utf-8"))
    assert match, "could not read the default port out of start.py's option resolution"
    return int(match.group(1))


def _tier_probe_port() -> int:
    match = re.search(r"^BASE_URL=\"http://127\.0\.0\.1:(\d+)/", TIER3.read_text("utf-8"), re.M)
    assert match, "tier3-artifact.sh must probe an explicit port on 127.0.0.1"
    return int(match.group(1))


def test_the_tier_probes_the_port_the_package_serves():
    served, probed = _packaged_default_port(), _tier_probe_port()
    assert probed == served, (
        f"tier3-artifact.sh probes :{probed} but the packaged service listens on "
        f":{served}. The tier reports this as 'service never became live', which "
        f"reads as a product failure and is not one."
    )


def test_the_package_tells_the_operator_the_port_it_serves():
    """The 'Next steps' text is the only port most operators will ever see."""
    served = _packaged_default_port()
    text = POSTINSTALL.read_text("utf-8")
    assert re.search(rf"http://localhost:{served}\b", text), (
        f"postinstall.sh does not point the operator at :{served}, the port "
        f"start.py actually binds"
    )
