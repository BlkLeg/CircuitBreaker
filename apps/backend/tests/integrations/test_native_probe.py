"""Tests for NativeProbePlugin.sync() — two live call sites use different config
shapes (see app/workers/integration_worker.py:_sync_one and
app/workers/integration_sync_worker.py:_run_sync_impl); both must work."""

from __future__ import annotations

from unittest.mock import patch

from app.db.models import IntegrationMonitor
from app.integrations.native_probe import NativeProbePlugin


def test_sync_accepts_worker_style_dict_config(db_session, factories):
    """integration_worker._sync_one passes a plain dict (no `.id`) plus `integration_id`
    as a kwarg — sync() must not assume `config` is an ORM row with attribute access."""
    intg = factories.integration(type="native")
    db_session.add(
        IntegrationMonitor(
            integration_id=intg.id,
            external_id="svc-1",
            name="test svc",
            probe_type="tcp",
            probe_target="127.0.0.1",
            probe_port=80,
        )
    )
    db_session.flush()

    plugin = NativeProbePlugin()
    config: dict = {"base_url": ""}

    with patch("app.integrations.native_probe._probe", return_value=("up", 1.0)):
        results = plugin.sync(config, db=db_session, integration_id=intg.id)

    assert len(results) == 1
    assert results[0].external_id == "svc-1"
    assert results[0].status == "up"


def test_sync_accepts_orm_row_config(db_session, factories):
    """integration_sync_worker._run_sync_impl passes the Integration ORM row
    directly (no integration_id kwarg) — sync() must fall back to config.id."""
    intg = factories.integration(type="native")
    db_session.add(
        IntegrationMonitor(
            integration_id=intg.id,
            external_id="svc-2",
            name="test svc 2",
            probe_type="tcp",
            probe_target="127.0.0.1",
            probe_port=80,
        )
    )
    db_session.flush()

    plugin = NativeProbePlugin()

    with patch("app.integrations.native_probe._probe", return_value=("up", 1.0)):
        results = plugin.sync(intg, db=db_session)

    assert len(results) == 1
    assert results[0].external_id == "svc-2"


# --- C3: the HTTP probe is an egress path, and was not treated as one --------
#
# `probe_target` is operator-supplied, stored unvalidated, and polled on a
# schedule. `_probe_http` reached `httpx_get` with PRIVATE_LAN_HTTP, for which
# `enforce_before_resolution` is deliberately a no-op — so nothing checked where
# the request actually went. Under CB_AIRGAP=true it went there anyway, every
# interval, and reported "down" while it did.


def test_an_external_target_is_refused_under_airgap(monkeypatch, caplog):
    """The air-gap half. A resolved public address must not be dialed, and the
    refusal must be visible: "down" alone is indistinguishable from a host that
    is simply switched off."""
    import logging

    from app.core import egress
    from app.integrations import native_probe

    monkeypatch.setattr(egress, "airgap_enabled", lambda: True)
    sent: list[str] = []
    monkeypatch.setattr(
        native_probe,
        "httpx_get",
        lambda url, **kw: sent.append(url),  # type: ignore[misc]
    )
    monkeypatch.setattr(
        "app.core.url_validation._resolve_host", lambda host, port, policy: ("93.184.216.34",)
    )

    with caplog.at_level(logging.WARNING):
        status, latency = native_probe._probe_http("https://collector.example.com/beacon")

    assert (status, latency) == ("down", None)
    assert sent == [], "the request must not leave the box"
    assert "refused HTTP probe" in caplog.text


def test_a_redirect_cannot_bounce_a_probe_into_link_local(monkeypatch):
    """The SSRF half. An allowed LAN target that answers with a redirect to the
    cloud metadata address must not be followed — which is what
    `follow_redirects=True` inside httpx did, with no re-validation per hop."""
    from app.integrations import native_probe

    class _Redirect:
        is_redirect = True
        status_code = 302
        headers = {"location": "http://169.254.169.254/latest/meta-data/"}

        class request:
            url = "http://192.168.1.10/"

    dialed: list[str] = []

    def _get(url, **kwargs):
        dialed.append(url)
        return _Redirect()

    monkeypatch.setattr(native_probe, "httpx_get", _get)
    monkeypatch.setattr("app.core.url_validation._resolve_host", lambda host, port, policy: (host,))

    status, latency = native_probe._probe_http("http://192.168.1.10/")

    assert (status, latency) == ("down", None)
    assert dialed == ["http://192.168.1.10/"], "the metadata hop must never be dialed"


def test_a_private_lan_target_still_probes(monkeypatch):
    """The gate must not break the product's actual job. Watching your own LAN
    is the whole point, so RFC1918 and loopback stay reachable."""
    from app.integrations import native_probe

    class _Ok:
        is_redirect = False
        status_code = 200

    monkeypatch.setattr(native_probe, "httpx_get", lambda url, **kw: _Ok())
    monkeypatch.setattr("app.core.url_validation._resolve_host", lambda host, port, policy: (host,))

    status, latency = native_probe._probe_http("http://192.168.1.10/health")

    assert status == "up"
    assert latency is not None
