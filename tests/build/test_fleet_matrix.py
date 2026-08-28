# tests/build/test_fleet_matrix.py
"""matrix.yaml is the single source of truth for what this project claims works.

Design §7.2: the matrix "feeds both the tier and the support-tier table in §8".
A row that names a tier the support table does not define, or an image without a
checksum, is a claim nobody can check. The image checksum matters most: the
golden image is fetched over the network into a cache outside the repo, and an
unverified image means the tier's "clean Fedora host" is whatever the mirror
served that day.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MATRIX = REPO_ROOT / "scripts" / "ci" / "fleet" / "matrix.yaml"

_REQUIRED = {
    "id", "distro", "format", "arch", "runner", "tier", "mode",
    "ssh_user", "cloud_init", "image_url",
}
_MODES = {"install", "upgrade"}
# Exactly one of these, and it must be the digest the distributor publishes.
# Fedora publishes sha256 in CHECKSUM; Debian publishes SHA512SUMS and nothing
# else. Insisting on one algorithm would have meant computing the other
# distributor's digest from a local download and calling it a pin -- which
# proves only that the file has not changed since it was fetched, and would pin
# a tampered image just as faithfully as a good one.
_DIGESTS = {"image_sha256": 64, "image_sha512": 128}


def _rows() -> list[dict[str, str]]:
    """Parse the matrix without taking a PyYAML dependency on the build suite.

    The format is deliberately a flat list of `key: value` blocks separated by
    `- ` markers; if it ever needs nesting, add PyYAML to the dev extra and
    rewrite this. Keeping it parseable by twenty lines of stdlib is worth more
    than the generality right now.
    """
    rows: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for raw in MATRIX.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("- "):
            current = {}
            rows.append(current)
            line = line.lstrip()[2:]
            if not line.strip():
                continue
        if current is None:
            continue
        key, _, value = line.strip().partition(":")
        current[key.strip()] = value.strip().strip('"')
    return rows


def test_matrix_exists():
    assert MATRIX.is_file(), f"{MATRIX} is missing"


def test_every_row_declares_every_required_field():
    for row in _rows():
        missing = _REQUIRED - set(row)
        assert not missing, f"row {row.get('id', '?')} is missing {sorted(missing)}"


def test_every_image_is_pinned_by_exactly_one_published_checksum():
    """An unpinned image makes 'clean host' mean 'whatever the mirror served
    today', which is not a controlled input. Two digests is not better than one:
    it invites the pair drifting apart, and leaves unstated which one the
    distributor actually published."""
    for row in _rows():
        present = {field for field in _DIGESTS if row.get(field)}
        assert len(present) == 1, (
            f"row {row['id']}: expected exactly one of {sorted(_DIGESTS)}, found {sorted(present)}"
        )
        field = present.pop()
        digest = row[field]
        width = _DIGESTS[field]
        assert re.fullmatch(rf"[0-9a-f]{{{width}}}", digest), (
            f"row {row['id']}: {field} must be {width} lowercase hex characters, got {digest!r}"
        )


def test_every_image_url_is_immutable():
    """`latest` moves under you. A release gate whose input can change without a
    commit is not a controlled input, and the failure it eventually produces
    looks like a corrupt download rather than a new upstream release."""
    for row in _rows():
        url = row["image_url"]
        assert "/latest/" not in url, (
            f"row {row['id']} pins a moving path: {url}. Use the dated or versioned "
            f"directory the distributor also publishes."
        )


def test_every_row_names_a_cloud_init_fixture_that_exists():
    """A row whose fixture is missing provisions a host with no database, and the
    package gets the blame for it."""
    for row in _rows():
        fixture = MATRIX.parent / "cloud-init" / row["cloud_init"]
        assert fixture.is_file(), f"row {row['id']} names a missing fixture: {fixture}"


def test_every_cloud_init_fixture_declares_the_units_it_started():
    """provision.sh re-verifies the fixture from the host rather than trusting the
    guest's readiness marker, and it reads the unit list out of the guest instead
    of hardcoding one. Slice 1 hardcoded Fedora's `postgresql && valkey`; Debian
    calls its redis unit redis-server, so the same literal would have failed a
    perfectly healthy guest."""
    for fixture in sorted((MATRIX.parent / "cloud-init").glob("*.user-data")):
        text = fixture.read_text(encoding="utf-8")
        assert "cb-fixture-services" in text, (
            f"{fixture.name} does not write /var/lib/cloud/cb-fixture-services, so "
            f"provisioning cannot verify what it claims to have started"
        )
        assert "cb-fixture-ready" in text, f"{fixture.name} writes no readiness marker"


def test_row_ids_are_unique_and_path_safe():
    """The id becomes a directory name under artifacts/diagnostics/."""
    ids = [row["id"] for row in _rows()]
    assert len(ids) == len(set(ids)), f"duplicate row ids: {ids}"
    for row_id in ids:
        assert re.fullmatch(r"[a-z0-9][a-z0-9.-]*", row_id), (
            f"row id {row_id!r} is not safe as a path component"
        )


def test_every_row_declares_a_known_mode():
    """`mode` is which half of the Tier 1 guarantee a row actually exercises.

    Phase 2's rows only installed and booted, and the tier field alone could not
    say so -- a `tier: 1` row published "install, boot, upgrade and roll back"
    while proving the first two. An unrecognised mode is a row whose claim
    nobody can check, so it fails rather than defaulting to the weaker one.
    """
    for row in _rows():
        assert row["mode"] in _MODES, (
            f"row {row['id']}: mode must be one of {sorted(_MODES)}, got {row['mode']!r}"
        )


def test_every_tier_1_row_has_an_upgrade_row_backing_it():
    """A tier 1 claim is "install, boot, upgrade and roll back". A tier 1 row with
    no upgrade counterpart is three quarters of a promise, which is the state
    Phase 2 shipped in and ADR 0005's in-force table exists to record."""
    rows = _rows()
    installs = {(r["distro"], r["format"], r["arch"]) for r in rows if r["tier"] == "1" and r["mode"] == "install"}
    upgrades = {(r["distro"], r["format"], r["arch"]) for r in rows if r["tier"] == "1" and r["mode"] == "upgrade"}
    unbacked = sorted(installs - upgrades)
    assert not unbacked, (
        f"tier 1 rows with no mode: upgrade counterpart: {unbacked}. Either add the "
        f"upgrade row or drop the row to tier 2, which claims only install and boot."
    )


def test_upgrade_rows_reuse_an_install_row_platform():
    """An upgrade row for a platform that is never install-tested would be
    asserting the harder claim without the easier one."""
    rows = _rows()
    installs = {(r["distro"], r["format"], r["arch"]) for r in rows if r["mode"] == "install"}
    for row in rows:
        if row["mode"] != "upgrade":
            continue
        key = (row["distro"], row["format"], row["arch"])
        assert key in installs, (
            f"row {row['id']} upgrades a platform with no install row: {key}"
        )


def test_phase_3_ships_the_slices_that_are_built():
    """Slice 1 added upgrade and rollback on the Fedora row Phase 2 built; slice 2
    added the deb family. arm64 and the tier 3 formats are slices 3 and 4, and a
    row added here without its fixture and its format support is a claim the tier
    cannot honour."""
    rows = {row["id"]: row for row in _rows()}
    assert set(rows) == {
        "fedora-rpm-amd64",
        "fedora-rpm-amd64-upgrade",
        "debian-deb-amd64",
        "debian-deb-amd64-upgrade",
    }, f"unexpected matrix rows: {sorted(rows)}"
    for row in rows.values():
        assert row["arch"] == "amd64", "arm64 is slice 4"
        assert row["runner"] == "local/qemu"


def test_every_declared_format_is_one_the_tier_script_can_install():
    """The matrix is a set of promises and tier3-artifact.sh is what keeps them.
    A row naming a format the script cannot install would fail at the point of
    use with an error about an artifact, not about the row that promised it."""
    tier = (MATRIX.parent.parent / "tier3-artifact.sh").read_text(encoding="utf-8")
    for row in _rows():
        fmt = row["format"]
        assert f"*.{fmt})" in tier, (
            f"row {row['id']} declares format {fmt}, which tier3-artifact.sh does not "
            f"dispatch on"
        )


def test_rows_sharing_a_platform_pin_the_same_image():
    """The install and upgrade rows are the same claim about the same host. Two
    different images would make a passing upgrade row say nothing about the
    install row's platform."""
    by_platform: dict[tuple[str, str], set[str]] = {}
    for row in _rows():
        digest = next(row[field] for field in _DIGESTS if row.get(field))
        by_platform.setdefault((row["distro"], row["arch"]), set()).add(digest)
    for platform, digests in by_platform.items():
        assert len(digests) == 1, (
            f"{platform} rows pin {len(digests)} different images: {sorted(digests)}"
        )
