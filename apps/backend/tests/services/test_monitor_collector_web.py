from unittest.mock import MagicMock, patch

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
