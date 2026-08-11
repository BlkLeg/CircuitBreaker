from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

from app.services.backup.s3_client import BackupS3Settings, S3Client


def _settings(endpoint_url: str | None) -> BackupS3Settings:
    return BackupS3Settings(
        bucket="backups",
        access_key_id="key",
        secret_access_key="secret-value",
        endpoint_url=endpoint_url,
    )


def test_s3_client_rejects_metadata_endpoint() -> None:
    with pytest.raises(ValueError):
        S3Client(_settings("http://169.254.169.254"))


def test_s3_client_rejects_private_dns_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_getaddrinfo(_host: str, *_args: object, **_kwargs: object) -> object:
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("10.0.0.4", 443))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    with pytest.raises(ValueError):
        S3Client(_settings("https://minio.example.test"))


def test_s3_client_accepts_public_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_getaddrinfo(_host: str, *_args: object, **_kwargs: object) -> object:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443))
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    with patch("app.services.backup.s3_client.boto3.client") as client:
        S3Client(_settings("https://s3.example.test"))

    assert client.call_args.kwargs["endpoint_url"] == "https://s3.example.test"
