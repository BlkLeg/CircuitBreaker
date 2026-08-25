"""Every way certbot can fail, and what the operator is told about it.

INC-07's dangerous half was that failures were not failures: `renew_certificate` caught
`FileNotFoundError`, logged a warning, and returned the unchanged certificate, so the API
answered 200 with the old expiry. Now that both creation and renewal go through
`issue_acme_certificate`, this is the one place those conversions happen — and the one
place that has to be tested, because a message that does not name the cause sends the
operator to the wrong system.

certbot is never invoked. The seam is `_run_certbot`, which every test replaces.
"""

from __future__ import annotations

import subprocess

import pytest

from app.services import acme_service
from app.services.certificate_service import CertificateRenewalError

_DOMAIN = "cb.example.org"


@pytest.fixture(autouse=True)
def _preflight_passes(monkeypatch):
    """Preflight refusals are tested in test_acme_preflight.py; these are the paths after."""
    monkeypatch.setenv("CB_TLS_EMAIL", "ops@example.org")
    monkeypatch.setattr(acme_service, "_self_check_http01", lambda domain: (True, "ok"))


@pytest.fixture(autouse=True)
def _tmp_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("CB_DATA_DIR", str(tmp_path))


def test_a_missing_certbot_says_so_rather_than_reporting_success(monkeypatch):
    def _absent(*args, **kwargs):
        raise FileNotFoundError("certbot")

    monkeypatch.setattr(acme_service, "_run_certbot", _absent)

    with pytest.raises(CertificateRenewalError, match="not available in this image"):
        acme_service.issue_acme_certificate(_DOMAIN)


def test_a_timeout_names_the_limit_it_hit(monkeypatch):
    def _slow(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="certbot", timeout=300)

    monkeypatch.setattr(acme_service, "_run_certbot", _slow)

    with pytest.raises(CertificateRenewalError, match="300"):
        acme_service.issue_acme_certificate(_DOMAIN)


def test_a_nonzero_exit_carries_the_stderr_tail(monkeypatch):
    """The CA's own words. "Issuance failed" is not something an operator can act on."""
    monkeypatch.setattr(
        acme_service,
        "_run_certbot",
        lambda *a, **k: subprocess.CompletedProcess(
            [], 1, "", "DNS problem: NXDOMAIN looking up A"
        ),
    )

    with pytest.raises(CertificateRenewalError, match="NXDOMAIN"):
        acme_service.issue_acme_certificate(_DOMAIN)


def test_success_certbot_did_not_write_is_still_a_failure(monkeypatch):
    """Exit 0 with no output file. Reading the old bytes here is the original defect."""
    monkeypatch.setattr(
        acme_service, "_run_certbot", lambda *a, **k: subprocess.CompletedProcess([], 0, "", "")
    )

    with pytest.raises(CertificateRenewalError, match="could not be read"):
        acme_service.issue_acme_certificate(_DOMAIN)


def test_the_argv_carries_the_account_email_and_the_webroot(monkeypatch):
    """INC-07's third cause was a hardcoded admin@localhost; CB_TLS_EMAIL is read now."""
    seen: list[list[str]] = []
    monkeypatch.setattr(
        acme_service,
        "_run_certbot",
        lambda argv, **k: seen.append(argv) or subprocess.CompletedProcess([], 1, "", "stop"),
    )

    with pytest.raises(CertificateRenewalError):
        acme_service.issue_acme_certificate(_DOMAIN)

    argv = seen[0]
    assert "ops@example.org" in argv
    assert "--webroot" in argv
    assert str(acme_service.webroot()) in argv
    # Never --standalone: it binds port 80 as a process running as breaker:1000, which is
    # INC-07's second cause and the reason the old renewal path could not work.
    assert "--standalone" not in argv


def test_staging_selects_the_staging_directory(monkeypatch):
    seen: list[list[str]] = []
    monkeypatch.setattr(
        acme_service,
        "_run_certbot",
        lambda argv, **k: seen.append(argv) or subprocess.CompletedProcess([], 1, "", "stop"),
    )

    with pytest.raises(CertificateRenewalError):
        acme_service.issue_acme_certificate(_DOMAIN, staging=True)

    assert acme_service.STAGING_DIRECTORY in seen[0]


def test_production_is_the_default(monkeypatch):
    """Staging certificates are untrusted; defaulting to them would look like success and
    fail in the browser."""
    seen: list[list[str]] = []
    monkeypatch.setattr(
        acme_service,
        "_run_certbot",
        lambda argv, **k: seen.append(argv) or subprocess.CompletedProcess([], 1, "", "stop"),
    )

    with pytest.raises(CertificateRenewalError):
        acme_service.issue_acme_certificate(_DOMAIN)

    assert acme_service.STAGING_DIRECTORY not in seen[0]


def test_certbot_writes_under_the_data_volume(monkeypatch):
    """The default /etc/letsencrypt is not writable by a non-root process."""
    seen: list[list[str]] = []
    monkeypatch.setattr(
        acme_service,
        "_run_certbot",
        lambda argv, **k: seen.append(argv) or subprocess.CompletedProcess([], 1, "", "stop"),
    )

    with pytest.raises(CertificateRenewalError):
        acme_service.issue_acme_certificate(_DOMAIN)

    assert "--config-dir" in seen[0]
    assert not any(arg == "/etc/letsencrypt" for arg in seen[0])
