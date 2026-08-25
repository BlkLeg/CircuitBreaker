"""The certbot arguments for DNS-01, and the credentials file behind them.

certbot takes provider credentials as a file path, not as arguments — which is the safer
shape, since an argv is world-readable in /proc. This pins the part that makes it actually
safer: the file is written 0600 inside the per-call temporary directory and is gone when the
call returns. A credentials file that outlived the issuance would be a plaintext zone
credential sitting on the data volume, which is exactly what encrypting the column avoided.

certbot itself is never invoked here. What is tested is every decision this codebase makes
around it, which is where the defects live.
"""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

import pytest

from app.services import acme_service
from app.services.certificate_service import CertificateRenewalError


@pytest.fixture
def tmp_dir(tmp_path):
    return str(tmp_path)


def _credentials_file(argv: list[str]) -> Path:
    """The path certbot is told to read, taken from the argv rather than assumed."""
    flag = next(arg for arg in argv if arg.endswith("-credentials"))
    return Path(argv[argv.index(flag) + 1])


def test_cloudflare_argv_names_the_plugin_and_a_credentials_file(monkeypatch, tmp_dir):
    monkeypatch.setattr(
        acme_service,
        "_dns_credentials",
        lambda: {"_provider": "cloudflare", "api_token": "cf-tok"},
    )

    argv = acme_service._dns_argv(tmp_dir)

    assert "--dns-cloudflare" in argv
    assert "dns_cloudflare_api_token = cf-tok" in _credentials_file(argv).read_text()


def test_the_credentials_file_is_not_readable_by_other_users(monkeypatch, tmp_dir):
    """It holds a zone credential in plaintext for the duration of the call."""
    monkeypatch.setattr(
        acme_service,
        "_dns_credentials",
        lambda: {"_provider": "cloudflare", "api_token": "cf-tok"},
    )

    argv = acme_service._dns_argv(tmp_dir)

    mode = stat.S_IMODE(os.stat(_credentials_file(argv)).st_mode)
    assert mode == 0o600, f"credentials file is {oct(mode)}"


def test_rfc2136_argv_carries_every_field_certbot_needs(monkeypatch, tmp_dir):
    monkeypatch.setattr(
        acme_service,
        "_dns_credentials",
        lambda: {
            "_provider": "rfc2136",
            "server": "ns1.example.com",
            "tsig_name": "cb-key",
            "tsig_secret": "s3cret",
        },
    )

    argv = acme_service._dns_argv(tmp_dir)
    written = _credentials_file(argv).read_text()

    assert "--dns-rfc2136" in argv
    assert "dns_rfc2136_server = ns1.example.com" in written
    assert "dns_rfc2136_name = cb-key" in written
    assert "dns_rfc2136_secret = s3cret" in written
    # Defaults, so that a form asking for three fields produces a working file.
    assert "dns_rfc2136_port = 53" in written
    assert "dns_rfc2136_algorithm = HMAC-SHA512" in written


def test_rfc2136_defaults_give_way_to_what_was_configured(monkeypatch, tmp_dir):
    monkeypatch.setattr(
        acme_service,
        "_dns_credentials",
        lambda: {
            "_provider": "rfc2136",
            "server": "ns1.example.com",
            "tsig_name": "cb-key",
            "tsig_secret": "s3cret",
            "port": 5353,
            "tsig_algorithm": "HMAC-SHA256",
        },
    )

    written = _credentials_file(acme_service._dns_argv(tmp_dir)).read_text()

    assert "dns_rfc2136_port = 5353" in written
    assert "dns_rfc2136_algorithm = HMAC-SHA256" in written


def test_missing_credentials_refuse_rather_than_write_an_empty_file(monkeypatch, tmp_dir):
    monkeypatch.setattr(acme_service, "_dns_credentials", lambda: None)

    with pytest.raises(CertificateRenewalError, match="not configured"):
        acme_service._dns_argv(tmp_dir)


def test_an_unsupported_provider_names_the_two_that_work(monkeypatch, tmp_dir):
    """INC-16 is in this same batch: a provider nobody has exercised is worse than none."""
    monkeypatch.setattr(
        acme_service,
        "_dns_credentials",
        lambda: {"_provider": "route53", "api_token": "x"},
    )

    with pytest.raises(CertificateRenewalError, match="Cloudflare"):
        acme_service._dns_argv(tmp_dir)


def test_an_incomplete_rfc2136_config_names_the_missing_field(monkeypatch, tmp_dir):
    """A KeyError here would reach the operator as an unhandled 500 with no cause."""
    monkeypatch.setattr(
        acme_service,
        "_dns_credentials",
        lambda: {"_provider": "rfc2136", "tsig_secret": "s3cret"},
    )

    with pytest.raises(CertificateRenewalError, match="server"):
        acme_service._dns_argv(tmp_dir)


def test_the_credentials_file_does_not_outlive_the_issuance(monkeypatch):
    """_dns_argv writes into the caller's TemporaryDirectory; leaving the block removes it."""
    monkeypatch.setattr(
        acme_service,
        "_dns_credentials",
        lambda: {"_provider": "cloudflare", "api_token": "cf-tok"},
    )

    with tempfile.TemporaryDirectory() as tmp:
        path = _credentials_file(acme_service._dns_argv(tmp))
        assert path.exists()

    assert not path.exists()
