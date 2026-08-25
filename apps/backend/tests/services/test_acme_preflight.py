"""Refuse before spending a Let's Encrypt rate-limit slot on a validation that cannot pass.

Production ACME allows five failed validations per hostname per hour. A homelab install with
a .local domain can never succeed, and must be told that instantly rather than after a
timeout.
"""

from __future__ import annotations

import pytest

from app.services import acme_service
from app.services.certificate_service import CertificateRenewalError


@pytest.fixture(autouse=True)
def _never_calls_certbot(monkeypatch):
    """A preflight that reaches certbot has already failed at its job."""

    def _boom(*args, **kwargs):
        raise AssertionError("preflight invoked certbot")

    monkeypatch.setattr(acme_service, "_run_certbot", _boom, raising=False)


@pytest.mark.parametrize(
    "domain",
    ["cb.local", "server.internal", "box.lan", "circuitbreaker", "192.168.1.10", "::1"],
)
def test_refuses_a_domain_no_public_ca_will_issue_for(domain, monkeypatch):
    monkeypatch.setenv("CB_TLS_EMAIL", "ops@example.com")

    with pytest.raises(CertificateRenewalError) as excinfo:
        acme_service.preflight(domain, "http-01")

    assert domain in str(excinfo.value)


def test_refuses_without_an_acme_email(monkeypatch):
    monkeypatch.delenv("CB_TLS_EMAIL", raising=False)

    with pytest.raises(CertificateRenewalError) as excinfo:
        acme_service.preflight("example.com", "http-01")

    assert "CB_TLS_EMAIL" in str(excinfo.value)


def test_http01_refuses_when_the_self_check_does_not_come_back(monkeypatch):
    """Catches the 301-to-HTTPS trap and split-horizon DNS before the CA does."""
    monkeypatch.setenv("CB_TLS_EMAIL", "ops@example.com")
    monkeypatch.setattr(acme_service, "_self_check_http01", lambda domain: (False, "404"))

    with pytest.raises(CertificateRenewalError) as excinfo:
        acme_service.preflight("example.com", "http-01")

    assert "/.well-known/acme-challenge/" in str(excinfo.value)


def test_dns01_refuses_without_provider_credentials(monkeypatch, db_session):
    monkeypatch.setenv("CB_TLS_EMAIL", "ops@example.com")
    monkeypatch.setattr(acme_service, "_dns_credentials", lambda: None)

    with pytest.raises(CertificateRenewalError) as excinfo:
        acme_service.preflight("example.com", "dns-01")

    assert "credential" in str(excinfo.value).lower()


def test_passes_for_a_public_domain_with_a_working_self_check(monkeypatch):
    monkeypatch.setenv("CB_TLS_EMAIL", "ops@example.com")
    monkeypatch.setattr(acme_service, "_self_check_http01", lambda domain: (True, "ok"))

    acme_service.preflight("example.com", "http-01")  # must not raise
