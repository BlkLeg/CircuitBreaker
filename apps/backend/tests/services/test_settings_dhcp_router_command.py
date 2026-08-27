# apps/backend/tests/services/test_settings_dhcp_router_command.py
"""B42: a router DHCP command that discovery will refuse must be refused at the save.

`_run_router_ssh_dhcp` validates `router_ssh_command` against a shell-metacharacter
blocklist and, when it fails, logs a warning and returns `[]`.  Nothing else happens:
the sweep reports no DHCP leases, the settings page reported the save as a success, and
the operator has no way to connect the two.  The command is stored, so the failure is
permanent and silent — every sweep from then on drops Tier 3 for a reason that only ever
appears in the worker log.

`dhcp_router_username` already got this treatment when B33 was fixed; this is the same
field family and the same argument.  The tests below deliberately drive the *whole*
forbidden-character set through the write path rather than a hand-picked `;`, because
the point of the fix is that the write path and the execution path share one validator
and cannot drift apart.
"""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.schemas.settings import AppSettingsUpdate
from app.services.discovery_dhcp import _FORBIDDEN_CMD_CHARS
from app.services.settings_service import update_settings


def test_saving_a_router_command_with_a_shell_metacharacter_is_refused():
    db = MagicMock()
    payload = AppSettingsUpdate(dhcp_router_command="cat /var/lib/misc/dnsmasq.leases; id")

    with pytest.raises(HTTPException) as exc_info:
        update_settings(db, payload)

    assert exc_info.value.status_code == 422
    assert "metacharacter" in str(exc_info.value.detail)
    db.commit.assert_not_called()


@pytest.mark.parametrize("bad_char", sorted(_FORBIDDEN_CMD_CHARS))
def test_the_write_path_refuses_exactly_what_the_ssh_path_refuses(bad_char: str):
    """One validator, two call sites — a character the sweep rejects cannot be saved.

    If this ever fails for a single character, the settings write has grown a second
    blocklist of its own and the two have drifted; re-use
    `discovery_dhcp._validate_router_command` instead of widening a copy.
    """
    db = MagicMock()
    payload = AppSettingsUpdate(dhcp_router_command=f"cat /tmp/leases{bad_char}")  # noqa: S108

    with pytest.raises(HTTPException) as exc_info:
        update_settings(db, payload)

    assert exc_info.value.status_code == 422
    db.commit.assert_not_called()


def _spy_on_the_shared_validator(monkeypatch) -> list[str]:
    """Record every value `update_settings` puts through the SSH path's validator.

    Asserting only that a value lands on the row does not pin this fix at all: delete the
    whole `dhcp_router_command` branch and the generic `setattr` tail at the bottom of
    `update_settings` stores exactly the same string, so the assertion goes green against
    a tree with no gate in it (that is precisely how the first two versions of the tests
    below were vacuous).  What distinguishes gated from ungated is not where the value
    ends up but whether it was *checked* on the way, so that is what these record.

    The branch imports `_validate_router_command` from `discovery_dhcp` at call time, on
    purpose, so patching the attribute on the module is enough — and if someone replaces
    that import with a second local copy of the blocklist, the spy stops seeing values
    and these tests fail, which is the drift B42 exists to prevent.
    """
    from app.services import discovery_dhcp

    checked: list[str] = []
    real = discovery_dhcp._validate_router_command

    def _spy(cmd: str) -> None:
        checked.append(cmd)
        real(cmd)

    monkeypatch.setattr(discovery_dhcp, "_validate_router_command", _spy)
    return checked


def test_the_commands_an_operator_actually_configures_still_save(monkeypatch):
    """The gate must not cost anybody a legitimate lease command — and must be the gate.

    Two failure modes in one test.  A command every real router answers has to survive the
    validator (an over-broad blocklist would strand the operator with no way to configure
    Tier 3 at all), and the save has to have gone *through* the validator rather than past
    it — see `_spy_on_the_shared_validator` for why the second half is not decoration.
    """
    checked = _spy_on_the_shared_validator(monkeypatch)
    commands = (
        "cat /var/lib/misc/dnsmasq.leases",
        "cat /tmp/dhcp.leases.dnsmasq",  # noqa: S108
        "show dhcp leases",
        "ubus call dhcp ipv4leases",
    )
    for command in commands:
        db = MagicMock()
        row = db.get.return_value

        update_settings(db, AppSettingsUpdate(dhcp_router_command=command))

        assert row.dhcp_router_command == command
        db.commit.assert_called_once()

    assert checked == list(commands), (
        "a router command reached the settings row without going through "
        "discovery_dhcp._validate_router_command — the B42 gate is not on this path"
    )


def test_clearing_the_router_command_is_allowed(monkeypatch):
    """An empty value falls back to the built-in default at sweep time, so let it save.

    Also pins that the empty string is legal *by the shared validator* rather than by a
    `if value:` short-circuit around it.  The distinction is the whole point of the fix:
    every value that reaches the column has been past the same check the SSH path runs,
    with no second rule about which values are worth checking that could drift from it.
    An `if value:` guard is one edit away from `if not value: raise`, which would strand
    an operator who wanted the default back.
    """
    checked = _spy_on_the_shared_validator(monkeypatch)
    db = MagicMock()
    row = db.get.return_value

    update_settings(db, AppSettingsUpdate(dhcp_router_command=""))

    assert row.dhcp_router_command == ""
    db.commit.assert_called_once()
    assert checked == [""], (
        "clearing the command bypassed discovery_dhcp._validate_router_command — the "
        "write path has grown its own opinion about which values need checking"
    )
