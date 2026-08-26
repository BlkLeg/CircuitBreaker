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


def test_cb_update_check_env_var_actually_disables_the_check(monkeypatch):
    """The documented control must work. Without the alias this returns True:
    Settings sets no env_prefix, so the bare field name binds instead."""
    from app.core.config import Settings

    monkeypatch.setenv("CB_UPDATE_CHECK", "false")
    assert Settings().update_check is False


async def test_a_304_after_a_transient_failure_does_not_pin_unreachable(monkeypatch):
    """200 -> connect error -> 304 must not leave status='unreachable' forever.

    The etag is earned by a 200 and kept across the failure, so the next call
    sends If-None-Match and GitHub answers 304 -- and keeps answering 304 until
    a new release is published, which can be months. `replace(_state,
    checked_at=...)` carried status='unreachable' through every one of those,
    so the Settings panel read "Could not reach the release source" immediately
    after a successful check. No test covered failure-then-304.
    """
    monkeypatch.setattr(update_check.settings, "app_version", "1.0.0-rc.2")
    monkeypatch.setattr(update_check.settings, "airgap", False)
    monkeypatch.setattr(update_check.settings, "update_check", True)

    monkeypatch.setattr(
        update_check,
        "_transport",
        lambda: _transport(lambda r: httpx.Response(200, json=RELEASES, headers={"ETag": "abc"})),
    )
    first = await update_check.refresh()
    assert first.status == "ok"

    def _down(request):
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(update_check, "_transport", lambda: _transport(_down))
    assert (await update_check.refresh()).status == "unreachable"

    seen = {}

    def _not_modified(request):
        seen["inm"] = request.headers.get("If-None-Match")
        return httpx.Response(304)

    monkeypatch.setattr(update_check, "_transport", lambda: _transport(_not_modified))
    third = await update_check.refresh()

    assert seen["inm"] == "abc", "the etag survives the failure and is still sent"
    assert third.status == "ok", "a 304 restores the status the etag was earned under"
    assert third.available == "1.0.0-rc.4"


async def test_a_304_restores_unknown_version_not_ok(monkeypatch):
    """The restored status is the etag's own, not a hardcoded 'ok'."""
    monkeypatch.setattr(update_check.settings, "app_version", "9.9.9-rc.1")
    monkeypatch.setattr(update_check.settings, "airgap", False)
    monkeypatch.setattr(update_check.settings, "update_check", True)
    monkeypatch.setattr(
        update_check,
        "_transport",
        lambda: _transport(lambda r: httpx.Response(200, json=RELEASES, headers={"ETag": "z"})),
    )
    assert (await update_check.refresh()).status == "unknown_version"

    monkeypatch.setattr(
        update_check, "_transport", lambda: _transport(lambda r: httpx.Response(304))
    )
    assert (await update_check.refresh()).status == "unknown_version"


async def test_the_release_list_is_requested_100_at_a_time(monkeypatch):
    """GitHub pages /releases at 30 by default. Past 30 published releases an
    older install falls off the list entirely and select_update answers
    unknown_version -- the reported field bug through a different door."""
    monkeypatch.setattr(update_check.settings, "app_version", "1.0.0-rc.2")
    monkeypatch.setattr(update_check.settings, "airgap", False)
    monkeypatch.setattr(update_check.settings, "update_check", True)
    seen = {}

    def _handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(200, json=RELEASES)

    monkeypatch.setattr(update_check, "_transport", lambda: _transport(_handler))
    await update_check.refresh()
    assert "per_page=100" in seen["url"], seen["url"]


async def test_the_configured_egress_proxy_is_honoured(monkeypatch):
    """MINOR-C: routed through outbound_async_client like every other caller,
    so an explicit CB_EGRESS_PROXY_URL applies and trust_env is pinned off."""
    captured = {}
    real = update_check.outbound_async_client

    def _spy(**kwargs):
        client = real(**kwargs)
        captured["mounts"] = dict(client._mounts)
        captured["trust_env"] = client.trust_env
        return client

    monkeypatch.setattr(update_check.settings, "app_version", "1.0.0-rc.2")
    monkeypatch.setattr(update_check.settings, "airgap", False)
    monkeypatch.setattr(update_check.settings, "update_check", True)
    monkeypatch.setattr(update_check.settings, "egress_proxy_url", "http://proxy.internal:3128")
    monkeypatch.setattr(update_check, "outbound_async_client", _spy)
    monkeypatch.setattr(
        update_check,
        "_transport",
        lambda: _transport(lambda r: httpx.Response(200, json=RELEASES)),
    )
    await update_check.refresh()

    assert captured["trust_env"] is False, "an ambient HTTPS_PROXY must not reach this caller"
    assert captured["mounts"], "the configured egress proxy must be mounted"
