"""`install.sh --docker` staged a world-readable .env and ignored --version.

Two defects in stage_docker_deploy, both observable by running it:

  * The generated .env holds CB_VAULT_KEY, CB_JWT_SECRET, CB_DB_PASSWORD and
    NATS_AUTH_TOKEN. It was created with a plain `cp` under the caller's umask,
    which on every distro this installer supports is 022 -- so 0644, readable
    by every account on the host. The vault key decrypts every stored
    credential and the JWT secret mints admin sessions. A chmod after the fact
    would still leave a window in which the secrets are world readable, so the
    file is created inside a tightened umask and the directory is locked before
    anything is written into it.

  * --version was parsed, and then not used on this path at all: the compose
    file and the root helper daemon came from `main` and the image from
    `:latest`. An operator who asked for 1.0.0 could get main's compose file
    driving whatever :latest pointed at, with a cb_helperd.py from a third
    revision running as root. --version now pins the ref for the assets and
    CB_TAG for the image, so the three cannot disagree.

stage_docker_deploy is run for real in a sandbox: docker, curl, systemctl and
the secret generators are stubbed, everything else -- the mkdir, the umask, the
cp, the appends, the branch on an existing .env -- is the shipped code. Modes
are read off the filesystem rather than matched in the source, and the fetched
URLs are read from the stub's log.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_SH = REPO_ROOT / "install.sh"


def _extract(name: str) -> str:
    """Pull one top-level function body out of install.sh by name."""
    body = re.search(
        rf"^{name}\(\) \{{\n.*?^\}}$", INSTALL_SH.read_text(), re.MULTILINE | re.DOTALL
    )
    assert body is not None, f"{name}() not found in install.sh"
    return body.group(0)


# Everything that would touch the host is replaced; the staging logic is not.
# `curl` logs the URL it was asked for and writes a placeholder so the
# subsequent cp of .env.example has something to copy. The secret generators
# return fixed strings so the test needs no openssl and the .env is
# byte-comparable.
HARNESS = """
set -euo pipefail
RED='' GREEN='' YELLOW='' CYAN='' BOLD='' DIM='' RESET=''
cb_header() { :; }
cb_section() { :; }
cb_step() { echo "STEP: $1"; }
cb_ok()   { echo "OK: $1"; }
cb_warn() { echo "WARN: $1"; }
cb_fail() { echo "FAIL: $1"; exit 1; }
cb_install_docker_if_missing() { :; }
cb_install_helper_daemon() { :; }
docker_target_user() { id -un; }
docker_target_home() { printf '%s' "$SANDBOX_HOME"; }
cb_generate_secret_base64() { printf 'b64secret%s' "$1"; }
cb_generate_secret_hex() { printf 'hexsecret%s' "$1"; }
docker() { echo "docker $*" >> "$SANDBOX_HOME/docker.log"; }
ip() { echo "1.1.1.1 via 10.0.0.1 dev eth0 src 10.0.0.2 uid 0"; }
curl() {
  local dest="" url=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      -o) dest="$2"; shift 2 ;;
      -*) shift ;;
      *)  url="$1"; shift ;;
    esac
  done
  echo "$url" >> "$SANDBOX_HOME/curl.log"
  printf '# stub for %s\\n' "$url" > "$dest"
}
"""


def stage(home: Path, *, version: str = "") -> subprocess.CompletedProcess:
    script = "\n".join(
        [
            HARNESS,
            f'CB_VERSION="{version}"',
            'CB_GITHUB_REPO="BlkLeg/CircuitBreaker"',
            _extract("stage_docker_deploy"),
            "stage_docker_deploy",
        ]
    )
    env = dict(os.environ, SANDBOX_HOME=str(home))
    result = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, env=env
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@pytest.fixture()
def home(tmp_path):
    # 022 is the umask every supported distro gives a login shell and the one
    # that made the generated .env 0644. Reproduce it explicitly so the test
    # does not silently pass under a hardened CI umask.
    previous = os.umask(0o022)
    try:
        yield tmp_path
    finally:
        os.umask(previous)


# --------------------------------------------------------------------------
# The .env holds four secrets and must never be readable by other accounts.
# --------------------------------------------------------------------------


def test_the_generated_env_is_not_readable_by_group_or_other(home):
    stage(home)
    env_file = home / ".circuitbreaker" / ".env"
    assert env_file.exists()
    assert mode(env_file) == 0o600, oct(mode(env_file))


def test_the_generated_env_really_does_hold_the_secrets(home):
    """Guards the test above: 0600 on an empty file would prove nothing."""
    stage(home)
    body = (home / ".circuitbreaker" / ".env").read_text()
    for key in ("CB_DB_PASSWORD", "CB_VAULT_KEY", "CB_JWT_SECRET", "NATS_AUTH_TOKEN"):
        assert f"{key}=" in body, body


def test_the_install_directory_is_not_traversable_by_other_accounts(home):
    stage(home)
    assert mode(home / ".circuitbreaker") == 0o700


def test_an_env_left_world_readable_by_an_earlier_install_is_repaired(home):
    """The preserve branch has to tighten what a previous run left behind."""
    install_dir = home / ".circuitbreaker"
    install_dir.mkdir()
    env_file = install_dir / ".env"
    env_file.write_text("CB_VAULT_KEY=from-an-earlier-run\n")
    env_file.chmod(0o644)

    result = stage(home)

    assert "CB_VAULT_KEY=from-an-earlier-run" in env_file.read_text()
    assert "Preserving existing" in result.stdout
    assert mode(env_file) == 0o600, oct(mode(env_file))


# --------------------------------------------------------------------------
# --version must pin the assets and the image to one revision.
# --------------------------------------------------------------------------


def fetched(home: Path) -> list[str]:
    return (home / ".circuitbreaker" / "curl.log").read_text().splitlines() \
        if (home / ".circuitbreaker" / "curl.log").exists() \
        else (home / "curl.log").read_text().splitlines()


def test_without_a_version_the_assets_come_from_main(home):
    stage(home)
    urls = fetched(home)
    assert urls, "stage_docker_deploy fetched nothing"
    assert all("/BlkLeg/CircuitBreaker/main/" in url for url in urls), urls


def test_without_a_version_no_tag_is_pinned(home):
    """Unset --version means the rolling default; CB_TAG stays at :latest."""
    stage(home)
    body = (home / ".circuitbreaker" / ".env").read_text()
    assert not any(line.startswith("CB_TAG=") for line in body.splitlines()), body


def test_a_version_pins_every_downloaded_asset_to_that_tag(home):
    stage(home, version="1.2.3")
    urls = fetched(home)
    assert urls, "stage_docker_deploy fetched nothing"
    assert all("/BlkLeg/CircuitBreaker/v1.2.3/" in url for url in urls), urls


def test_a_version_pins_the_helper_daemon_too(home):
    """cb_helperd.py runs as root; a drifted copy is the worst of the three."""
    stage(home, version="1.2.3")
    helper = [url for url in fetched(home) if url.endswith("cb_helperd.py")]
    assert helper == [
        "https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/v1.2.3/deploy/helper/cb_helperd.py"
    ], fetched(home)


def test_a_version_pins_the_image_tag_in_the_env(home):
    """docker-compose.yml reads ${CB_TAG:-latest}; unset means the image floats."""
    stage(home, version="1.2.3")
    body = (home / ".circuitbreaker" / ".env").read_text()
    assert "CB_TAG=1.2.3" in body, body


def test_a_leading_v_on_the_version_is_not_doubled(home):
    """`--version v1.2.3` must not produce a `vv1.2.3` ref or a `vX` image tag."""
    stage(home, version="v1.2.3")
    urls = fetched(home)
    assert all("/BlkLeg/CircuitBreaker/v1.2.3/" in url for url in urls), urls
    assert "CB_TAG=1.2.3" in (home / ".circuitbreaker" / ".env").read_text()


def test_a_preserved_env_warns_that_the_pin_was_not_applied(home):
    """Silently leaving CB_TAG unset is the drift this finding is about."""
    install_dir = home / ".circuitbreaker"
    install_dir.mkdir()
    (install_dir / ".env").write_text("CB_VAULT_KEY=from-an-earlier-run\n")

    result = stage(home, version="1.2.3")

    assert "CB_TAG=1.2.3" in result.stdout, result.stdout
    assert "WARN:" in result.stdout, result.stdout
