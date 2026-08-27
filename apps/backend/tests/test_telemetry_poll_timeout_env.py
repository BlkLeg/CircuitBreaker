"""The manual-poll device timeout must survive a mistyped environment variable.

R7, a regression introduced by the B07 fix (745a99b9). Before that commit the
manual-poll path read no environment variable at all; the fix added
``_device_timeout_seconds()`` with a bare ``int(os.environ.get(...))``, so a
``CB_TELEMETRY_DEVICE_TIMEOUT_SECONDS`` of ``"20s"`` — or ``"twenty"``, or a
trailing space picked up from a compose file — raises ``ValueError`` before the
device is ever contacted and turns every "poll now" click into a 500.

A malformed knob must degrade to the documented default, loudly in the log and
quietly in the response. It must not take the feature down.
"""

from __future__ import annotations

import pytest

from app.api.telemetry import _device_timeout_seconds

_ENV = "CB_TELEMETRY_DEVICE_TIMEOUT_SECONDS"
# The documented default, duplicated on purpose: if someone changes the default
# in telemetry.py this test should say so rather than silently follow along.
_DEFAULT_SECONDS = 20


@pytest.mark.parametrize(
    "raw",
    [
        "twenty",
        "20s",
        "",
        "  ",
        "30.5",
        "0x20",
    ],
)
def test_a_malformed_device_timeout_falls_back_to_the_default(monkeypatch, raw):
    """Every value ``int()`` refuses must produce the default, never an exception."""
    monkeypatch.setenv(_ENV, raw)

    assert _device_timeout_seconds() == _DEFAULT_SECONDS


def test_a_well_formed_device_timeout_is_still_honoured(monkeypatch):
    """The guard must not swallow the knob it exists to protect."""
    monkeypatch.setenv(_ENV, "45")
    assert _device_timeout_seconds() == 45

    # Whitespace is what an operator's editor leaves behind, not a typo.
    monkeypatch.setenv(_ENV, " 45 ")
    assert _device_timeout_seconds() == 45


def test_the_five_second_floor_survives_the_guard(monkeypatch):
    """A numeric-but-tiny value still clamps: an instant poll looks like a dead device."""
    monkeypatch.setenv(_ENV, "0")
    assert _device_timeout_seconds() == 5

    monkeypatch.setenv(_ENV, "-99")
    assert _device_timeout_seconds() == 5


def test_an_absent_knob_is_the_default(monkeypatch):
    monkeypatch.delenv(_ENV, raising=False)
    assert _device_timeout_seconds() == _DEFAULT_SECONDS


@pytest.mark.asyncio
async def test_a_malformed_device_timeout_does_not_500_the_manual_poll(
    client, auth_headers, factories, monkeypatch
):
    """End to end: the bad knob must not reach the operator as a 500.

    This is the shape R7 actually takes in production — nobody calls
    ``_device_timeout_seconds`` by hand, they click "poll now" and get an
    Internal Server Error with a ``ValueError`` in the log and no hint that the
    cause is a typo in their own environment file.
    """
    import app.services.telemetry_service as telemetry_service

    monkeypatch.setenv(_ENV, "twenty")
    hw = factories.hardware(
        telemetry_config={"profile": "snmp_generic", "host": "10.0.0.11", "enabled": True}
    )
    factories.session.commit()

    monkeypatch.setattr(
        "app.api.telemetry.poll_hardware",
        lambda _hw, _vault: {"status": "healthy", "data": {"cpu_pct": 3.5}},
    )
    monkeypatch.setattr(telemetry_service, "cache_telemetry", _anoop)
    monkeypatch.setattr(telemetry_service, "publish_telemetry", _anoop)

    resp = await client.post(f"/api/v1/hardware/{hw.id}/telemetry/poll", headers=auth_headers)

    assert resp.status_code == 200, f"malformed timeout knob broke the poll: {resp.text}"
    assert resp.json()["status"] == "healthy"


async def _anoop(*_args, **_kwargs):
    return None
