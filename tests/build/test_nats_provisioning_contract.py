"""One pinned NATS, and a dependency the package manager can enforce.

Tier 3 found a Fedora install that could never start: nfpm.yaml lists
`nats-server` under `recommends`, Fedora has no such package, and the service
refuses to run without a broker. `recommends` is the wrong strength for a
component the application will not start without — a weak dependency lets the
package manager install something that cannot run, which is precisely what
happened.

The chosen shape, after review:

* Where the distro ships nats-server (Debian/Ubuntu, Alpine), depend on it. The
  distro then owns CVE updates, which is the policy Dockerfile.mono states
  explicitly ("version pinning on apt packages is intentionally avoided to keep
  CVE fixes current"). Vendoring a pinned copy everywhere would have inverted
  that and made a NATS CVE fix wait on a Circuit Breaker release.
* Where it does not (Fedora), ship it as a SEPARATE package. Separate keeps the
  vendored CVE surface out of the application package and lets an operator
  running an external or clustered broker simply not install it.
* Pin that vendored copy in one file, shared with deploy/setup.sh, so the
  unverified "latest" download disappears rather than gaining a fourth variant.
* Wants=, not Requires=. Since the bounded-connect fix, a missing broker
  degrades rather than hangs, and CB_NATS_URL exists so the broker can live on
  another host entirely — §7.4's multi-host agents depend on that staying
  first-class.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PIN = REPO_ROOT / "packaging" / "nats-server.pin"
NFPM = REPO_ROOT / "nfpm.yaml"
NFPM_NATS = REPO_ROOT / "packaging" / "nfpm-nats.yaml"
SETUP = REPO_ROOT / "deploy" / "setup.sh"
UNIT = REPO_ROOT / "packaging" / "circuit-breaker.service"


def _pin() -> dict[str, str]:
    values = {}
    for line in PIN.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if "=" in line:
            k, _, v = line.partition("=")
            values[k.strip()] = v.strip()
    return values


def test_the_pin_names_a_version_and_a_digest_per_arch():
    pin = _pin()
    assert re.fullmatch(r"\d+\.\d+\.\d+", pin.get("NATS_VERSION", "")), pin
    for arch in ("amd64", "arm64"):
        digest = pin.get(f"NATS_SHA256_{arch}", "")
        assert re.fullmatch(r"[0-9a-f]{64}", digest), (
            f"NATS_SHA256_{arch} must be a 64-char sha256; an unverified binary "
            f"installed as root is not a dependency, it is a supply chain"
        )


def test_setup_sh_no_longer_resolves_latest_from_the_network():
    """A release gate cannot depend on what GitHub called 'latest' that day."""
    text = SETUP.read_text(encoding="utf-8")
    assert "releases/latest" not in text, (
        "deploy/setup.sh must install the pinned version from "
        "packaging/nats-server.pin, not whatever the GitHub API returns"
    )
    assert "nats-server.pin" in text, "setup.sh must read the shared pin"


def test_setup_sh_verifies_what_it_downloads():
    text = SETUP.read_text(encoding="utf-8")
    assert re.search(r"sha256sum\b.*(-c|--check)", text) or "NATS_SHA256_" in text, (
        "the downloaded tarball must be checked against the pinned digest"
    )


def test_distro_platforms_depend_on_nats_rather_than_recommending_it():
    """The app will not start without a broker, so a weak dependency lets the
    package manager install something that cannot run."""
    text = NFPM.read_text(encoding="utf-8")
    for platform in ("deb", "apk"):
        block = re.search(rf"^  {platform}:\n((?:    .*\n|\n)*)", text, re.M)
        assert block, f"no {platform} override block in nfpm.yaml"
        body = block.group(1)
        depends = re.search(r"depends:\n((?:      - .*\n)*)", body)
        assert depends and "nats-server" in depends.group(1), (
            f"{platform} ships on a distro that packages nats-server; it belongs "
            f"in depends, not recommends"
        )


def test_rpm_does_not_recommend_a_package_fedora_does_not_have():
    text = NFPM.read_text(encoding="utf-8")
    block = re.search(r"^  rpm:\n((?:    .*\n|\n)*)", text, re.M)
    assert block, "no rpm override block"
    recommends = re.search(r"recommends:\n((?:      - .*\n)*)", block.group(1))
    if recommends:
        assert "nats-server" not in recommends.group(1), (
            "Fedora has no nats-server package, so recommending one is a "
            "dependency that silently does nothing; the circuit-breaker-nats "
            "subpackage is what provides it there"
        )


def test_a_separate_subpackage_provides_the_vendored_broker():
    assert NFPM_NATS.is_file(), (
        "the vendored broker belongs in its own package so its CVE surface stays "
        "separable and an external-broker deployment can decline it"
    )
    text = NFPM_NATS.read_text(encoding="utf-8")
    assert re.search(r"^name:\s*circuit-breaker-nats\s*$", text, re.M)


def test_the_app_unit_wants_the_broker_rather_than_requiring_it():
    """Requires= would make every install run its own broker and turn the
    clustered topology in §7.4 into a special case."""
    text = UNIT.read_text(encoding="utf-8")
    assert "Requires=circuit-breaker-nats" not in text, (
        "a missing broker degrades since the bounded-connect fix; Requires= "
        "would forbid pointing CB_NATS_URL at another host"
    )
    assert re.search(r"^Wants=.*circuit-breaker-nats", text, re.M), (
        "the unit should Wants= the bundled broker so it starts alongside it "
        "when installed, without depending on it"
    )
