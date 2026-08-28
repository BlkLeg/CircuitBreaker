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

_REQUIRED = {"id", "distro", "format", "arch", "runner", "tier", "image_url", "image_sha256"}


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


def test_phase_2_ships_exactly_the_fedora_rpm_row():
    """Phase 2 is one row by design (§11). Phase 3 is what adds breadth; a row
    added here without its provisioning is a claim the tier cannot support."""
    rows = _rows()
    assert len(rows) == 1, f"Phase 2 defines one row, found {len(rows)}"
    row = rows[0]
    assert row["distro"].startswith("fedora")
    assert row["format"] == "rpm"
    assert row["arch"] == "amd64"
    assert row["runner"] == "local/qemu"
