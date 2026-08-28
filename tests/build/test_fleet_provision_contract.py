# tests/build/test_fleet_provision_contract.py
"""Provisioning must be unprivileged, ephemeral, and honest about its tools.

Three properties, each of which has a way of quietly not holding:

* **Unprivileged.** The whole point of choosing raw QEMU over libvirt was that
  /dev/kvm is world-writable here, so no contributor needs a daemon, a group, or
  a password to run the release gate. A `sudo` creeping into this script takes
  that away silently -- it will still work on the machine that added it.
* **Ephemeral.** The guarantee that every run starts from a clean host is
  `qemu-img create -b`: a copy-on-write overlay over a read-only golden image.
  Booting the golden image directly would work exactly once and then quietly
  test a dirty host forever after.
* **Honest.** A gate that cannot find qemu must fail, not skip.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FLEET = REPO_ROOT / "scripts" / "ci" / "fleet"
PROVISION = FLEET / "provision.sh"
USER_DATA = FLEET / "cloud-init" / "fedora.user-data"


def test_provision_script_exists_and_is_executable():
    assert PROVISION.is_file(), f"{PROVISION} is missing"
    assert PROVISION.stat().st_mode & 0o111, f"{PROVISION} is not executable"


def test_provision_uses_strict_bash():
    text = PROVISION.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in text


def test_provision_never_escalates_privilege():
    """/dev/kvm is 0666 on the fleet host; needing sudo would mean the gate only
    runs for whoever configured the machine."""
    offenders = []
    for lineno, line in enumerate(
        PROVISION.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if line.strip().startswith("#"):
            continue
        # Strip quoted spans before matching. cb::require_tool's hints legitimately
        # tell the *operator* to run `sudo dnf install qemu-img`; that is
        # documentation, not escalation. Matching raw lines flagged those hints and
        # would have been "fixed" by making the hints less useful.
        bare = re.sub(r'"[^"]*"|\'[^\']*\'', "", line)
        if re.search(r"(^|\s)(sudo|pkexec|doas)\s", bare):
            offenders.append(f"{lineno}: {line.strip()}")
    assert not offenders, (
        "provisioning must run unprivileged -- raw QEMU over libvirt was chosen "
        "precisely so it could:\n  " + "\n  ".join(offenders)
    )


def test_provision_boots_a_copy_on_write_overlay():
    """`-b golden.qcow2` is what makes 'clean host' structural. Without it the
    first run mutates the golden image and every later run tests residue."""
    text = PROVISION.read_text(encoding="utf-8")
    assert "qemu-img create" in text, "no overlay is created"
    assert re.search(r"qemu-img create[^\n]*-b ", text), (
        "the overlay must be backed by the golden image (-b), not a fresh disk"
    )


def test_provision_fails_closed_on_missing_tools():
    text = PROVISION.read_text(encoding="utf-8")
    for tool in ("qemu-system-x86_64", "genisoimage", "ssh", "curl"):
        assert f"cb::require_tool {tool}" in text, (
            f"{tool} must be required with cb::require_tool so a missing tool "
            f"exits 127 rather than producing a confusing failure later"
        )


def test_provision_verifies_the_image_checksum():
    """An image fetched over the network and not verified is an uncontrolled
    input to every assertion downstream of it."""
    text = PROVISION.read_text(encoding="utf-8")
    assert "sha256sum" in text or "sha256" in text
    assert "image_sha256" in text, "the digest must come from matrix.yaml, not be hardcoded"


def test_cloud_init_provisions_the_database_the_package_names():
    """packaging/postinstall.sh generates an env pointing at
    postgresql://circuitbreaker:changeme@127.0.0.1:5432/circuitbreaker, and the
    rpm only *recommends* postgresql-server -- nothing runs initdb or creates
    that role. Provisioning it is a test precondition (autopkgtest's Depends:
    split); asserting the package works against it is the test."""
    text = USER_DATA.read_text(encoding="utf-8")
    assert "postgresql-setup --initdb" in text
    assert "CREATE ROLE circuitbreaker" in text, "the role the package's own env names"
    assert "createdb -O circuitbreaker circuitbreaker" in text
    # valkey, not redis: Fedora 44 ships no `redis` package. It is wire-compatible
    # and listens on 6379, so the package's CB_REDIS_URL is unchanged. Naming the
    # wrong package is not a partial failure -- dnf resolves `packages:` as one
    # transaction, so one bad name took postgresql-server down with it.
    assert "valkey" in text
    assert "\n  - redis\n" not in text, "redis is not a Fedora 44 package; valkey replaces it"


def test_the_readiness_marker_cannot_be_reached_by_a_failed_fixture():
    """The marker provision.sh waits on must mean the work actually happened.

    cloud-init's runcmd does not stop at the first failing entry, so a list of
    independent commands ending in `touch <marker>` writes that marker even when
    every step before it failed -- which is exactly what happened on the first
    boot: nothing was installed, and provision.sh reported a ready host. Same
    defect as a security gate reporting a missing scanner as a clean scan.
    """
    text = USER_DATA.read_text(encoding="utf-8")
    assert "cb-fixture-ready" in text
    assert "set -euo pipefail" in text or "-euo" in text, (
        "the fixture must run as one fail-fast script so the marker is "
        "unreachable when a precondition fails"
    )
    body = text[text.index("runcmd:"):]
    marker_at = body.index("touch /var/lib/cloud/cb-fixture-ready")
    for required in ("systemctl is-active --quiet postgresql",
                     "systemctl is-active --quiet valkey"):
        assert required in body, f"fixture must verify {required!r} before declaring ready"
        assert body.index(required) < marker_at, (
            f"{required!r} must run BEFORE the readiness marker, not after"
        )


def test_cloud_init_does_not_install_the_candidate():
    """The artifact under test is pushed by dispatch.sh and installed by
    tier3-artifact.sh. A VM that arrives with it already installed is not
    testing an install."""
    text = USER_DATA.read_text(encoding="utf-8")
    assert ".rpm" not in text, "cloud-init must not install the candidate package"
    assert "circuit-breaker.service" not in text


def test_provision_verifies_the_fixture_itself_rather_than_trusting_the_marker():
    """A marker is the guest's claim about itself; the host must check.

    The fixture is now fail-fast, so cb-fixture-ready is trustworthy today. That
    is a property of one file that anyone can edit, and provision.sh returning
    "ready" is what every assertion downstream is built on. So the host confirms
    the two services it actually needs before printing its contract line -- if
    the marker and reality ever diverge again, provisioning fails instead of
    handing tier3-artifact.sh a broken machine and letting the package take the
    blame.
    """
    text = PROVISION.read_text(encoding="utf-8")
    assert "systemctl is-active" in text, (
        "provision.sh must verify the fixture services from the host, not rely "
        "solely on the guest-written readiness marker"
    )
    marker_at = text.index("cb-fixture-ready")
    verify_at = text.index("systemctl is-active")
    assert verify_at > marker_at, (
        "the independent check belongs after the marker wait, as confirmation "
        "of it rather than a replacement for it"
    )


def test_provision_cleans_up_its_own_scratch_when_it_fails():
    """A failed provision must not leak the VM dir it created.

    provision.sh mktemps a directory, writes a disk overlay into it and boots a
    VM from it, then hands the path to its caller. dispatch.sh traps and destroys
    -- but only once it has read that path, so any failure *before* the handoff
    leaves the directory and possibly a running VM with no owner. Two were found
    on disk after the -nographic and continuation-chain failures. The design's
    "destroy always" is not satisfied by a cleanup that only runs on the paths
    that got far enough to tell someone about it.
    """
    text = PROVISION.read_text(encoding="utf-8")
    assert "trap " in text, "provision.sh must clean up its own scratch on failure"
    assert "cb::fleet_scratch_cleanup" in text or "rm -rf \"$VM_DIR\"" in text
