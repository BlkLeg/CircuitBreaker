"""The default-on outbound call must stay documented, and documented correctly.

The release check is the only network request a stock install makes without an
operator configuring anything, and it discloses the running version to a third
party once a day. `docs/deployment-security.md` had an "Outbound egress" section
that did not mention it at all. That matters more here than in most projects:
`main.py` deliberately withholds the version from unauthenticated callers as
fingerprinting material, so a silent daily disclosure of the same value needs to
be stated, not discovered.

These tests pin the doc against the code rather than against a fixed string, so
changing the endpoint or the cadence in `update_check.py` fails here until the
security doc is updated with it.

`docs/installation/configuration.md` also filed `CB_UPDATE_CHECK` under
"Discovery", which is where an operator looks for scan settings, not for
outbound egress.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UPDATE_CHECK = REPO_ROOT / "apps/backend/src/app/core/update_check.py"
SECURITY_DOC = REPO_ROOT / "docs/deployment-security.md"
CONFIG_DOC = REPO_ROOT / "docs/installation/configuration.md"


def _const(name: str) -> str:
    source = UPDATE_CHECK.read_text(encoding="utf-8")
    match = re.search(rf"^{name} = (.+?)(?:\s+#.*)?$", source, re.MULTILINE)
    assert match, f"{name} not found in update_check.py"
    return match.group(1).strip()


def test_the_security_doc_names_the_url_the_code_actually_calls():
    url = _const("GITHUB_RELEASES_URL").strip("\"'")
    assert url in SECURITY_DOC.read_text(encoding="utf-8"), (
        f"docs/deployment-security.md must name {url}; the endpoint changed in "
        "update_check.py without the egress disclosure following it."
    )


def test_the_security_doc_states_what_is_disclosed():
    doc = SECURITY_DOC.read_text(encoding="utf-8")
    assert "User-Agent: circuit-breaker/<version>" in doc
    assert "source IP" in doc
    # The point of the paragraph: a version disclosure, said out loud.
    assert re.search(r"disclos\w+ to a third party", doc), (
        "the disclosure must be stated plainly, not implied"
    )


def test_the_security_doc_states_the_cadence_the_code_uses():
    doc = SECURITY_DOC.read_text(encoding="utf-8")
    assert _const("CHECK_INTERVAL_S") == "24 * 60 * 60"
    assert _const("JITTER_S") == "30 * 60"
    assert "24 hours" in doc
    assert "30 minutes" in doc and "jitter" in doc


def test_the_security_doc_lists_every_way_to_turn_it_off():
    doc = SECURITY_DOC.read_text(encoding="utf-8")
    for control in ("CB_UPDATE_CHECK=false", "CB_AIRGAP=true", "airgap_mode"):
        assert control in doc, f"{control} disables the check and must be documented as such"


def test_the_security_doc_says_it_honours_the_egress_proxy():
    doc = SECURITY_DOC.read_text(encoding="utf-8")
    assert "outbound_async_client" in UPDATE_CHECK.read_text(encoding="utf-8")
    assert "CB_EGRESS_PROXY_URL" in doc.split("#### The daily release check")[1].split("###")[0]


def test_cb_update_check_is_not_filed_under_discovery():
    """It is outbound egress. An operator reading "Discovery" is looking for
    scan settings, and will not find an internet call there."""
    doc = CONFIG_DOC.read_text(encoding="utf-8")
    discovery = doc.split("### Discovery")[1].split("###")[0]
    assert "CB_UPDATE_CHECK" not in discovery
    assert "CB_UPDATE_CHECK" in doc, "the variable must still be documented somewhere"


def test_the_config_doc_no_longer_claims_cb_airgap_only_affects_scans():
    """CB_AIRGAP now genuinely disables the release check too (it did not before
    the AliasChoices fix, because only the un-prefixed AIRGAP bound)."""
    doc = CONFIG_DOC.read_text(encoding="utf-8")
    airgap_row = next(ln for ln in doc.splitlines() if ln.startswith("| `CB_AIRGAP`"))
    assert "release check" in airgap_row
