from unittest.mock import MagicMock, patch

import httpx as _httpx
import pytest

from app.services.monitoring.collectors import COLLECTORS, web


def _mock_response(status=200, text="hello world", json_data=None):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    resp.json.return_value = json_data if json_data is not None else {}
    return resp


def _run(params, resp):
    with patch.object(web, "_request", return_value=(resp, 42.0)):
        return web.collect_http("192.0.2.5", params)


def test_http_registered():
    assert COLLECTORS["http"] is web.collect_http


def test_status_in_default_range():
    result = _run({"url": "http://x/"}, _mock_response(204))
    assert result.up is True
    assert "204" in result.msg


def test_status_outside_range():
    result = _run({"url": "http://x/"}, _mock_response(500))
    assert result.up is False
    assert "500" in result.msg


def test_explicit_status_ranges():
    result = _run(
        {"url": "http://x/", "accepted_statuses": ["301", "400-403"]}, _mock_response(403)
    )
    assert result.up is True


def test_keyword_found():
    result = _run({"url": "http://x/", "keyword": "world"}, _mock_response(200, "hello world"))
    assert result.up is True


def test_keyword_missing():
    result = _run({"url": "http://x/", "keyword": "absent"}, _mock_response(200, "hello world"))
    assert result.up is False
    assert "keyword" in result.msg


def test_keyword_inverted():
    result = _run(
        {"url": "http://x/", "keyword": "error", "keyword_invert": True},
        _mock_response(200, "all fine"),
    )
    assert result.up is True


def test_json_path_match():
    result = _run(
        {"url": "http://x/", "json_path": "status.state", "expected_value": "ok"},
        _mock_response(200, "{}", {"status": {"state": "ok"}}),
    )
    assert result.up is True


def test_json_path_mismatch():
    result = _run(
        {"url": "http://x/", "json_path": "status.state", "expected_value": "ok"},
        _mock_response(200, "{}", {"status": {"state": "degraded"}}),
    )
    assert result.up is False


def test_network_error_is_down_not_raise():
    with patch.object(web, "_request", side_effect=OSError("refused")):
        result = web.collect_http("192.0.2.5", {"url": "http://x/"})
    assert result.up is False
    assert result.samples[0].error_reason == "http_error"


def test_status_range_parser():
    assert web._status_accepted(204, ["200-299"]) is True
    assert web._status_accepted(301, ["200-299"]) is False
    assert web._status_accepted(301, ["200-299", "301"]) is True
    assert web._status_accepted(200, []) is True  # empty → default 200-299


# ── SEC-12: a monitor URL is attacker-influenced input ───────────────────────
# Whoever can create a monitor picks the host, method, headers and body, so the
# check itself must refuse the targets an SSRF wants while still allowing the
# LAN and localhost targets the product exists to watch.


def test_request_refuses_link_local_metadata_target():
    with pytest.raises(ValueError, match="Monitor URL"):
        web._request("http://169.254.169.254/latest/meta-data/", {})


def test_request_allows_private_and_loopback_targets():
    sent = []

    def _fake_request(method, url, **kwargs):
        sent.append(url)
        resp = MagicMock(spec=_httpx.Response)
        resp.is_redirect = False
        resp.status_code = 200
        return resp

    for target in ("http://10.0.0.9/health", "http://127.0.0.1:8080/health"):
        with patch.object(_httpx, "request", side_effect=_fake_request):
            web._request(target, {})

    assert sent == ["http://10.0.0.9/health", "http://127.0.0.1:8080/health"]


def test_redirect_into_link_local_is_refused():
    def _fake_request(method, url, **kwargs):
        resp = MagicMock(spec=_httpx.Response)
        resp.is_redirect = True
        resp.status_code = 302
        resp.headers = {"location": "http://169.254.169.254/latest/meta-data/"}
        resp.request = MagicMock()
        resp.request.url = url
        return resp

    with patch.object(_httpx, "request", side_effect=_fake_request):
        with pytest.raises(ValueError, match="Monitor URL"):
            web._request("http://10.0.0.9/health", {"follow_redirects": True})
