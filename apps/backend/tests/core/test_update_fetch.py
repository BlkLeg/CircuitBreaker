"""Fetching is allowed to fail; it is never allowed to lie or to block."""

import httpx
import pytest

from app.core import update_check


@pytest.fixture(autouse=True)
def _clean_cache():
    update_check.reset_cache()
    yield
    update_check.reset_cache()


RELEASES = [
    {"tag_name": "v1.0.0-rc.4", "draft": False},
    {"tag_name": "v1.0.0-rc.2", "draft": False},
    {"tag_name": "v0.3.4", "draft": False},
]


def _transport(handler):
    return httpx.MockTransport(handler)


async def test_rc2_learns_about_rc4(monkeypatch):
    monkeypatch.setattr(update_check.settings, "app_version", "1.0.0-rc.2")
    monkeypatch.setattr(update_check.settings, "airgap", False)
    monkeypatch.setattr(update_check.settings, "update_check", True)
    monkeypatch.setattr(
        update_check,
        "_transport",
        lambda: _transport(lambda r: httpx.Response(200, json=RELEASES)),
    )
    state = await update_check.refresh()
    assert state.status == "ok"
    assert state.available == "1.0.0-rc.4"
    assert state.checked_at is not None


async def test_airgap_opens_no_socket(monkeypatch):
    monkeypatch.setattr(update_check.settings, "airgap", True)

    def _boom():
        raise AssertionError("airgap must short-circuit before any socket")

    monkeypatch.setattr(update_check, "_transport", _boom)
    state = await update_check.refresh()
    assert state.status == "airgap"
    assert state.available is None


async def test_opt_out_opens_no_socket(monkeypatch):
    monkeypatch.setattr(update_check.settings, "airgap", False)
    monkeypatch.setattr(update_check.settings, "update_check", False)

    def _boom():
        raise AssertionError("CB_UPDATE_CHECK=false must short-circuit")

    monkeypatch.setattr(update_check, "_transport", _boom)
    state = await update_check.refresh()
    assert state.status == "disabled"


async def test_network_failure_is_unreachable_not_up_to_date(monkeypatch):
    monkeypatch.setattr(update_check.settings, "app_version", "1.0.0-rc.2")
    monkeypatch.setattr(update_check.settings, "airgap", False)
    monkeypatch.setattr(update_check.settings, "update_check", True)

    def _handler(request):
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(update_check, "_transport", lambda: _transport(_handler))
    state = await update_check.refresh()
    assert state.status == "unreachable"
    assert state.available is None


async def test_a_previous_answer_survives_a_later_failure(monkeypatch):
    monkeypatch.setattr(update_check.settings, "app_version", "1.0.0-rc.2")
    monkeypatch.setattr(update_check.settings, "airgap", False)
    monkeypatch.setattr(update_check.settings, "update_check", True)
    monkeypatch.setattr(
        update_check,
        "_transport",
        lambda: _transport(lambda r: httpx.Response(200, json=RELEASES)),
    )
    await update_check.refresh()

    def _handler(request):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(update_check, "_transport", lambda: _transport(_handler))
    await update_check.refresh()
    assert update_check.current_state().available == "1.0.0-rc.4"


async def test_304_keeps_the_cached_answer(monkeypatch):
    monkeypatch.setattr(update_check.settings, "app_version", "1.0.0-rc.2")
    monkeypatch.setattr(update_check.settings, "airgap", False)
    monkeypatch.setattr(update_check.settings, "update_check", True)
    monkeypatch.setattr(
        update_check,
        "_transport",
        lambda: _transport(lambda r: httpx.Response(200, json=RELEASES, headers={"ETag": "abc"})),
    )
    await update_check.refresh()

    seen = {}

    def _handler(request):
        seen["inm"] = request.headers.get("If-None-Match")
        return httpx.Response(304)

    monkeypatch.setattr(update_check, "_transport", lambda: _transport(_handler))
    state = await update_check.refresh()
    assert seen["inm"] == "abc"
    assert state.available == "1.0.0-rc.4"


async def test_garbage_payload_does_not_raise(monkeypatch):
    monkeypatch.setattr(update_check.settings, "app_version", "1.0.0-rc.2")
    monkeypatch.setattr(update_check.settings, "airgap", False)
    monkeypatch.setattr(update_check.settings, "update_check", True)
    monkeypatch.setattr(
        update_check,
        "_transport",
        lambda: _transport(lambda r: httpx.Response(200, json={"message": "rate limited"})),
    )
    state = await update_check.refresh()
    assert state.status == "unreachable"


def test_state_before_any_check_is_never_checked():
    assert update_check.current_state().status == "never_checked"
