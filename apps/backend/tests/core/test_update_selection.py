"""The channel rule, driven by the shared fixture (spec section 10)."""

import json
from pathlib import Path

import pytest

from app.core.update_check import UpdateVerdict, channels_from_releases, select_update

_CASES = json.loads(
    (Path(__file__).resolve().parents[4] / "tests/fixtures/update-channel-cases.json").read_text()
)["cases"]


@pytest.mark.parametrize("case", _CASES, ids=[c["name"] for c in _CASES])
def test_shared_fixture_cases(case):
    verdict = select_update(case["current"], case["channels"], case["withdrawn"])
    assert verdict == UpdateVerdict(
        status=case["expected"]["status"],
        channel=case["expected"]["channel"],
        available=case["expected"]["available"],
    )


def test_channels_from_releases_splits_by_kind():
    releases = [
        {"tag_name": "v1.0.0-rc.4", "draft": False},
        {"tag_name": "v1.0.0-rc.2", "draft": False},
        {"tag_name": "v0.3.4", "draft": False},
    ]
    assert channels_from_releases(releases) == {
        "stable": ["0.3.4"],
        "prerelease": ["1.0.0-rc.4", "1.0.0-rc.2", "0.3.4"],
    }


def test_channels_from_releases_skips_drafts_and_junk():
    releases = [
        {"tag_name": "v9.9.9", "draft": True},
        {"tag_name": "", "draft": False},
        {"draft": False},
        {"tag_name": "v0.3.4", "draft": False},
    ]
    assert channels_from_releases(releases) == {"stable": ["0.3.4"], "prerelease": ["0.3.4"]}


def test_rc2_against_the_live_release_shape_is_offered_rc4():
    """End-to-end over the two pure functions, using the real API shape."""
    releases = [
        {"tag_name": "v1.0.0-rc.4", "draft": False},
        {"tag_name": "v1.0.0-rc.2", "draft": False},
        {"tag_name": "v1.0.0-rc.1", "draft": False},
        {"tag_name": "v0.3.4", "draft": False},
    ]
    verdict = select_update("1.0.0-rc.2", channels_from_releases(releases))
    assert verdict.available == "1.0.0-rc.4"


def test_a_v_prefixed_current_is_still_offered_the_upgrade():
    """MINOR-A. APP_VERSION is an operator-settable env var and the plan's own
    verification step sets it, so a `v`-prefixed value reaching select_update is
    a real shape. `channels_from_releases` v-strips the tags, so comparing
    `current` raw made the membership test miss and returned unknown_version --
    silently offering nothing, the exact stranding this branch exists to end."""
    releases = [
        {"tag_name": "v1.0.0-rc.4", "draft": False},
        {"tag_name": "v1.0.0-rc.2", "draft": False},
        {"tag_name": "v0.3.4", "draft": False},
    ]
    verdict = select_update("v1.0.0-rc.2", channels_from_releases(releases))
    assert verdict == UpdateVerdict(status="ok", channel="prerelease", available="1.0.0-rc.4")


def test_a_v_prefixed_stable_current_lands_in_the_stable_channel():
    verdict = select_update("v0.3.4", {"stable": ["0.3.4", "0.3.3"], "prerelease": []})
    assert verdict == UpdateVerdict(status="ok", channel="stable", available=None)


def test_v_prefixed_channel_entries_are_normalised_too():
    """Callers other than channels_from_releases may pass raw tags."""
    verdict = select_update("1.0.0-rc.2", {"prerelease": ["v1.0.0-rc.4", "v1.0.0-rc.2"]})
    assert verdict.available == "1.0.0-rc.4"


def test_a_v_prefixed_withdrawal_still_blocks():
    verdict = select_update(
        "1.0.0-rc.2",
        {"prerelease": ["1.0.0-rc.4", "1.0.0-rc.2"]},
        withdrawn=["v1.0.0-rc.4"],
    )
    assert verdict.available is None


def test_an_unparseable_channel_returns_unknown_version_not_valueerror():
    """MINOR-B. `max()` over an empty list raised ValueError, which refresh()
    swallowed into status 'unreachable' -- a lie, the network was fine."""
    verdict = select_update("nightly", {"prerelease": ["nightly"]})
    assert verdict == UpdateVerdict(status="unknown_version", channel="prerelease", available=None)
