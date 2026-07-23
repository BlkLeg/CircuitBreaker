from unittest.mock import patch

import pytest

from app.db.models import AppSettings
from app.services import helper_client


def _set_auth_enabled(db_session, value: bool) -> None:
    cfg = db_session.query(AppSettings).first()
    cfg.auth_enabled = value
    db_session.flush()


@pytest.mark.asyncio
async def test_configure_domain_success(client, db_session):
    _set_auth_enabled(db_session, False)
    with patch(
        "app.services.auth_service.helper_client.configure_domain",
        return_value={
            "applied": True,
            "fqdn": "cb.example.com",
            "app_url": "https://cb.example.com/",
        },
    ) as mock_configure:
        resp = await client.post("/api/v1/bootstrap/domain", json={"fqdn": "cb.example.com"})

    assert resp.status_code == 200
    body = resp.json()
    assert body == {"fqdn": "cb.example.com", "app_url": "https://cb.example.com/"}
    mock_configure.assert_called_once_with("cb.example.com")

    settings = db_session.query(AppSettings).first()
    assert settings.fqdn == "cb.example.com"


@pytest.mark.asyncio
async def test_configure_domain_rejected_after_bootstrap_complete(client, db_session):
    _set_auth_enabled(db_session, True)
    with patch("app.services.auth_service.helper_client.configure_domain") as mock_configure:
        resp = await client.post("/api/v1/bootstrap/domain", json={"fqdn": "cb.example.com"})

    assert resp.status_code == 409
    mock_configure.assert_not_called()


@pytest.mark.asyncio
async def test_configure_domain_rejects_invalid_fqdn(client, db_session):
    _set_auth_enabled(db_session, False)
    with patch("app.services.auth_service.helper_client.configure_domain") as mock_configure:
        resp = await client.post("/api/v1/bootstrap/domain", json={"fqdn": "127.0.0.1"})

    assert resp.status_code == 422
    mock_configure.assert_not_called()


@pytest.mark.asyncio
async def test_configure_domain_returns_503_when_helper_unavailable(client, db_session):
    _set_auth_enabled(db_session, False)
    with patch(
        "app.services.auth_service.helper_client.configure_domain",
        side_effect=helper_client.HelperUnavailable("no socket"),
    ):
        resp = await client.post("/api/v1/bootstrap/domain", json={"fqdn": "cb.example.com"})

    assert resp.status_code == 503
    settings = db_session.query(AppSettings).first()
    assert settings.fqdn is None


@pytest.mark.asyncio
async def test_configure_domain_returns_422_on_helper_action_error(client, db_session):
    _set_auth_enabled(db_session, False)
    with patch(
        "app.services.auth_service.helper_client.configure_domain",
        side_effect=helper_client.HelperActionError("nginx -t failed: syntax error"),
    ):
        resp = await client.post("/api/v1/bootstrap/domain", json={"fqdn": "cb.example.com"})

    assert resp.status_code == 422
    assert "syntax error" in resp.json()["detail"]
    settings = db_session.query(AppSettings).first()
    assert settings.fqdn is None
