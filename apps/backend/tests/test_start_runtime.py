import argparse
import os
from pathlib import Path

import pytest

from app.start import configure_runtime, load_native_config


def test_load_native_config_parses_basic_scalars(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "host: 127.0.0.1",
                "port: 9443",
                "workers: 2",
                "tls_enabled: true",
                'tls_cert_file: "/tmp/server.crt"',
                "tls_key_file: /tmp/server.key",
            ]
        ),
        encoding="utf-8",
    )

    config = load_native_config(config_path)

    assert config["host"] == "127.0.0.1"
    assert config["port"] == 9443
    assert config["workers"] == 2
    assert config["tls_enabled"] is True
    assert config["tls_cert_file"] == "/tmp/server.crt"
    assert config["tls_key_file"] == "/tmp/server.key"


def test_configure_runtime_sets_defaults_from_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    data_dir = tmp_path / "data"
    static_dir = tmp_path / "frontend"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "host: 127.0.0.1",
                "port: 8181",
                f"data_dir: {data_dir}",
                f"static_dir: {static_dir}",
                "workers: 3",
            ]
        ),
        encoding="utf-8",
    )

    for key in (
        "APP_VERSION",
        "CB_DATA_DIR",
        "DATABASE_URL",
        "UPLOADS_DIR",
        "STATIC_DIR",
        "HOST",
        "PORT",
        "UVICORN_WORKERS",
    ):
        monkeypatch.delenv(key, raising=False)

    options = configure_runtime(
        argparse.Namespace(
            config=str(config_path),
            host=None,
            port=None,
            workers=None,
            ssl_certfile=None,
            ssl_keyfile=None,
            version=False,
        )
    )

    assert options["host"] == "127.0.0.1"
    assert options["port"] == 8181
    assert options["workers"] == 3
    assert data_dir.exists()
    assert (data_dir / "uploads").exists()
    assert Path(os.environ["CB_DATA_DIR"]) == data_dir
    assert os.environ["STATIC_DIR"] == str(static_dir)
    assert os.environ["DATABASE_URL"].endswith("app.db")


def test_configure_runtime_requires_both_tls_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("tls_enabled: true\ntls_cert_file: /tmp/server.crt\n", encoding="utf-8")

    monkeypatch.delenv("CB_TLS_KEY_FILE", raising=False)

    with pytest.raises(SystemExit, match="Both TLS cert and key files are required"):
        configure_runtime(
            argparse.Namespace(
                config=str(config_path),
                host=None,
                port=None,
                workers=None,
                ssl_certfile=None,
                ssl_keyfile=None,
                version=False,
            )
        )
