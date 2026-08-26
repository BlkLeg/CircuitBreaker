"""Ordering for this project's version scheme.

`1.0.0-rc.10` vs `1.0.0-rc.4` is the case that kills naive implementations:
string comparison and `split(".")` both rank rc.10 below rc.4. The old
update check truncated the prerelease away entirely, so rc.2 and rc.4 were
equal and no rc user was ever offered an upgrade.
"""

import importlib.util
from pathlib import Path

import pytest

from app.core import version

_ROOT = Path(__file__).resolve().parents[4]


def _load_release_channel():
    """scripts/ is a directory of entrypoints, not an importable package."""
    spec = importlib.util.spec_from_file_location(
        "release_channel", _ROOT / "scripts/release_channel.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ORDERED = ["0.3.3", "0.3.4", "1.0.0-rc.2", "1.0.0-rc.4", "1.0.0-rc.10", "1.0.0"]


def test_scheme_orders_correctly():
    assert sorted(ORDERED, key=version.parse) == ORDERED


def test_rc10_is_newer_than_rc4():
    assert version.is_newer("1.0.0-rc.10", "1.0.0-rc.4")
    assert not version.is_newer("1.0.0-rc.4", "1.0.0-rc.10")


def test_the_reported_regression():
    """An rc.2 instance must recognise rc.4 as newer."""
    assert version.is_newer("1.0.0-rc.4", "1.0.0-rc.2")


def test_stable_outranks_its_own_candidates():
    assert version.is_newer("1.0.0", "1.0.0-rc.4")


def test_v_prefix_is_tolerated():
    assert version.is_newer("v1.0.0-rc.4", "1.0.0-rc.2")


@pytest.mark.parametrize("raw", ["", "dev-abc1234", "not-a-version", "unknown"])
def test_unparseable_is_never_newer(raw):
    assert version.parse(raw) is None
    assert not version.is_newer(raw, "1.0.0-rc.2")


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1.0.0", False),
        ("0.3.4", False),
        ("1.0.0-rc.4", True),
        ("1.0.0-alpha.1", True),
        # packaging would call these stable; the project's allowlist rule does not.
        ("1.0", True),
        ("1.0.0.post1", True),
        ("dev-abc1234", True),
        ("unknown", True),
    ],
)
def test_prerelease_uses_the_projects_allowlist_rule(raw, expected):
    assert version.is_prerelease(raw) is expected


@pytest.mark.parametrize(
    "raw",
    [
        "1.0.0",
        "0.3.4",
        "1.0.0-rc.4",
        "1.0.0-alpha.1",
        "1.0",
        "1.0.0.post1",
        "dev-abc1234",
        # v-prefixed: the tag shape. This test advertises a "must not drift"
        # guarantee, and these were precisely the inputs where the two
        # implementations drifted -- app.core.version stripped the `v`,
        # scripts/release_channel.py did not, so `v1.0.0` was stable to one and
        # a prerelease to the other.
        "v1.0.0",
        "v0.3.4",
        "v1.0.0-rc.4",
        "V1.0.0",
    ],
)
def test_agrees_with_release_channel(raw):
    """Build-time and run-time must not drift on what counts as a prerelease."""
    assert version.is_prerelease(raw) is _load_release_channel().is_prerelease(raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("v1.0.0", "1.0.0"), ("V1.0.0-rc.4", "1.0.0-rc.4"), ("  1.0.0  ", "1.0.0"), ("", "")],
)
def test_clean_strips_whitespace_and_a_leading_v(raw, expected):
    assert version.clean(raw) == expected
