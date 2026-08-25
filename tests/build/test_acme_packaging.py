"""certbot has to be in the image, and its inputs have to reach the process.

INC-07 listed four independent reasons Let's Encrypt could not work in a shipped
deployment. Two of them are packaging rather than code, and neither would fail any test
that existed:

  * certbot was in no image, so `certificate_service` shelled out to a binary that was
    never there.
  * `CB_TLS_EMAIL` was advertised in docker/.env.example and read by nothing. It is read
    now — and it still never reached the container, because docker-compose.yml did not
    pass it through, and never reached a native install, because the installer collects
    the same address under a different name.

Everything here is a static read of the build inputs. Building the image is Task 9 Step 4's
manual check; these are the assertions that keep it true afterwards.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

ACME_REQUIREMENTS = ROOT / "apps" / "backend" / "requirements-acme.txt"

# Every runtime directory certbot needs under the data volume, and why:
#   acme-challenge — the HTTP-01 webroot both nginx and the app serve
#   letsencrypt    — account key, config and logs; the default /etc/letsencrypt is not
#                    writable by a non-root process, which is INC-07's reason #2
#   tmp            — where the credentials file and certbot's output live for one call
ACME_DIRS = ("acme-challenge", "letsencrypt", "tmp")


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_the_pins_name_certbot_and_exactly_two_plugins():
    """A third plugin here without a matching SECRET_KEYS entry and _dns_argv branch is a
    provider the UI can select and issuance cannot use."""
    pins = {
        line.split("==")[0]
        for line in ACME_REQUIREMENTS.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }

    assert pins == {"certbot", "certbot-dns-cloudflare", "certbot-dns-rfc2136"}


def test_every_acme_pin_is_exact():
    """The rest of this repo's Python dependencies are pinned; an unpinned certbot would
    make the image's ACME behaviour depend on when it was built."""
    for line in ACME_REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        assert re.fullmatch(r"[a-z0-9-]+==\d+\.\d+\.\d+", line.strip()), line


@pytest.mark.parametrize("dockerfile", ["Dockerfile", "Dockerfile.mono"])
def test_both_images_install_the_acme_requirements(dockerfile):
    content = _read(dockerfile)

    assert "requirements-acme.txt" in content, (
        f"{dockerfile}: certbot is not installed, so issuance raises "
        "'certbot is not available in this image' — INC-07's first cause"
    )
    # Copied as well as referenced: a -r against a file that was never COPYed fails the
    # build, but only at build time, and only for whichever image forgot it.
    assert content.count("requirements-acme.txt") >= 2, (
        f"{dockerfile}: requirements-acme.txt must be both COPYed and installed"
    )


@pytest.mark.parametrize("directory", ACME_DIRS)
def test_the_mono_entrypoint_creates_the_runtime_directories(directory):
    content = _read("docker/entrypoint-mono.sh")

    assert f"/{directory}" in content, (
        f"docker/entrypoint-mono.sh does not create $CB_DATA_DIR/{directory}"
    )


@pytest.mark.parametrize("directory", ACME_DIRS)
def test_the_native_installer_creates_the_runtime_directories(directory):
    content = _read("deploy/setup.sh")

    assert f'["${{CB_DATA_DIR}}/{directory}"]' in content, (
        f"deploy/setup.sh does not create and own $CB_DATA_DIR/{directory}"
    )


def test_compose_passes_the_acme_email_into_the_container():
    """.env.example has advertised CB_TLS_EMAIL since before anything read it. Now that
    something does, the value has to actually arrive."""
    assert "CB_TLS_EMAIL=${CB_TLS_EMAIL:-}" in _read("docker-compose.yml")


def test_the_native_install_writes_the_acme_email():
    """The installer collects it as --email/CB_EMAIL; the application reads CB_TLS_EMAIL."""
    assert "CB_TLS_EMAIL=${CB_EMAIL}" in _read("deploy/misc/.env.template")


def test_the_env_example_does_not_call_the_email_optional():
    """It reads as optional only while nothing reads it. Issuance now refuses without it."""
    content = _read("docker/.env.example")
    block = content[content.index("CB_TLS_EMAIL") - 300 : content.index("CB_TLS_EMAIL")]

    assert "only needed" not in block
    assert "Required" in block
