"""Endpoints are operator-authored, so every field is validated and ids are ours."""

from __future__ import annotations

import pytest

from app.services import agent_endpoints


def test_mints_an_id_when_absent():
    result = agent_endpoints.normalize_endpoints([{"label": "LAN", "url": "https://10.0.0.5"}])
    assert result[0]["id"]
    assert result[0]["label"] == "LAN"


def test_keeps_an_existing_id_so_install_commands_keep_resolving():
    result = agent_endpoints.normalize_endpoints(
        [{"id": "keepme", "label": "LAN", "url": "https://10.0.0.5"}]
    )
    assert result[0]["id"] == "keepme"


def test_rejects_a_non_http_scheme():
    with pytest.raises(ValueError, match="scheme"):
        agent_endpoints.normalize_endpoints([{"label": "bad", "url": "file:///etc/passwd"}])


def test_rejects_a_blank_label():
    with pytest.raises(ValueError, match="label"):
        agent_endpoints.normalize_endpoints([{"label": "  ", "url": "https://10.0.0.5"}])


def test_rejects_duplicate_ids():
    with pytest.raises(ValueError, match="duplicate"):
        agent_endpoints.normalize_endpoints(
            [
                {"id": "same", "label": "a", "url": "https://a.example.com"},
                {"id": "same", "label": "b", "url": "https://b.example.com"},
            ]
        )


def test_strips_a_trailing_slash_so_urls_concatenate_predictably():
    result = agent_endpoints.normalize_endpoints([{"label": "LAN", "url": "https://10.0.0.5/"}])
    assert result[0]["url"] == "https://10.0.0.5"
