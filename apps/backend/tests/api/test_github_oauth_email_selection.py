"""GitHub OAuth used the email as the account key without proving the account held it.

`github_callback` looked for a primary-and-verified address and, failing that, fell back
to `emails[0]["email"]` with no verification check. Anyone may add any address to a
GitHub account, so an attacker who added a target's work address to their own account
and left it unverified matched the target's Circuit Breaker user on that email and signed
in as them — account takeover with no interaction from the target.

`select_github_email` is the whole of the decision, so it is asserted directly rather
than through a stubbed OAuth round trip.
"""

from __future__ import annotations

import pytest

from app.api.auth_oauth import select_github_email

_TARGET = "ops@corp.example"


def test_an_unverified_address_is_never_selected():
    """The defect, stated as its payload: one unverified address and nothing else."""
    assert select_github_email([{"email": _TARGET, "primary": True, "verified": False}]) is None, (
        "an unverified address was accepted as the account key"
    )


def test_an_unverified_address_does_not_win_over_a_verified_one():
    emails = [
        {"email": _TARGET, "primary": True, "verified": False},
        {"email": "attacker@example.test", "primary": False, "verified": True},
    ]

    assert select_github_email(emails) == "attacker@example.test"


def test_the_primary_verified_address_wins():
    emails = [
        {"email": "alt@example.test", "primary": False, "verified": True},
        {"email": "main@example.test", "primary": True, "verified": True},
    ]

    assert select_github_email(emails) == "main@example.test"


def test_a_verified_address_is_used_when_none_is_flagged_primary():
    """GitHub does not always flag one; a verified address is still proof of holding it."""
    emails = [{"email": "only@example.test", "verified": True}]

    assert select_github_email(emails) == "only@example.test"


@pytest.mark.parametrize(
    "emails",
    [
        [],
        [{"email": "a@example.test", "verified": False}],
        [
            {"email": "a@example.test", "primary": True, "verified": False},
            {"email": "b@example.test", "primary": False, "verified": False},
        ],
    ],
)
def test_no_verified_address_yields_none(emails):
    """The caller turns None into its existing 400 rather than signing anyone in."""
    assert select_github_email(emails) is None
