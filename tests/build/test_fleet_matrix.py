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

_REQUIRED = {"id", "distro", "format", "arch", "runner", "tier", "mode", "image_url", "image_sha256"}
_MODES = {"install", "upgrade"}


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


def test_every_image_is_pinned_by_checksum():
    """An unpinned image makes 'clean Fedora host' mean 'whatever the mirror
    served today', which is not a controlled input."""
    for row in _rows():
        digest = row["image_sha256"]
        assert re.fullmatch(r"[0-9a-f]{64}", digest), (
            f"row {row['id']}: image_sha256 must be a 64-character hex sha256, got {digest!r}"
        )


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


def test_phase_3_ships_the_fedora_rpm_install_and_upgrade_rows():
    """Phase 3's first slice is upgrade and rollback on the row Phase 2 built.
    Breadth -- debian/deb, arm64, the tier 3 formats -- is the later slices, and
    a row added here without its cloud-init fixture is a claim the tier cannot
    support."""
    rows = {row["id"]: row for row in _rows()}
    assert set(rows) == {"fedora-rpm-amd64", "fedora-rpm-amd64-upgrade"}, (
        f"unexpected matrix rows: {sorted(rows)}"
    )
    for row in rows.values():
        assert row["distro"].startswith("fedora")
        assert row["format"] == "rpm"
        assert row["arch"] == "amd64"
        assert row["runner"] == "local/qemu"
    assert rows["fedora-rpm-amd64"]["mode"] == "install"
    assert rows["fedora-rpm-amd64-upgrade"]["mode"] == "upgrade"


def test_rows_sharing_a_platform_pin_the_same_image():
    """The install and upgrade rows are the same claim about the same host. Two
    different images would make a passing upgrade row say nothing about the
    install row's platform."""
    by_platform: dict[tuple[str, str], set[str]] = {}
    for row in _rows():
        by_platform.setdefault((row["distro"], row["arch"]), set()).add(row["image_sha256"])
    for platform, digests in by_platform.items():
        assert len(digests) == 1, (
            f"{platform} rows pin {len(digests)} different images: {sorted(digests)}"
        )
