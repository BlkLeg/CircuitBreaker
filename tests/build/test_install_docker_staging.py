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
import shlex
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


def stage(
    home: Path,
    *,
    version: str = "",
    overrides: str = "",
    check: bool = True,
) -> subprocess.CompletedProcess:
    """Run the shipped stage_docker_deploy against the stub harness.

    `overrides` is appended after HARNESS so a single test can replace one stub
    -- the `ip` tests below swap in a failing one -- without every other test
    inheriting the change. `check=False` is for the tests whose whole subject is
    whether the function survives to its last line, which cannot assert on the
    exit status if the helper has already asserted it away.
    """
    script = "\n".join(
        [
            HARNESS,
            overrides,
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
    if check:
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


# --------------------------------------------------------------------------
# The summary block is the payoff for the whole stage and must always print.
# --------------------------------------------------------------------------
#
# stage_docker_deploy ends by working out an address to show the operator:
#
#     host_ip="$(ip route get 1.1.1.1 2>/dev/null | awk '/src/ {print $7; exit}')"
#
# `ip route get 1.1.1.1` exits non-zero when iproute2 is not installed and on
# any host with no route to that address -- an air-gapped LAN deployment, which
# is squarely this product's audience. The 2>/dev/null hides the message but not
# the status, `pipefail` promotes it past the awk that would otherwise have
# returned a clean 0, and as a bare assignment under `set -e` that ended the
# installer right there. Right there is *after* `docker compose up -d` returned
# and cb-helperd was installed: the stack was up, and the operator saw the last
# `[OK]` followed by a silent non-zero exit, with the install directory, the
# access URLs and the useful-commands block never printed. The reasonable
# conclusion from that screen is that the install failed, and the reasonable
# next action is to tear down a deployment that is actually working.
#
# The address is cosmetic; nothing downstream consumes it. Nothing in this tail
# may abort.

# Stands in for a host with no route to 1.1.1.1: `ip` writes to stderr (which
# the shipped code discards) and exits 2, exactly as iproute2 does.
IP_UNREACHABLE = """
ip() { echo "RTNETLINK answers: Network is unreachable" >&2; return 2; }
"""

# Stands in for a host with no iproute2 at all: `ip` is simply not a command.
IP_MISSING = """
ip() { echo "bash: ip: command not found" >&2; return 127; }
"""


@pytest.mark.parametrize(
    "override", [IP_UNREACHABLE, IP_MISSING], ids=["no-route", "no-iproute2"]
)
def test_the_deployment_summary_survives_an_unusable_ip_command(home, override):
    """The stage must reach its end even when the address lookup cannot."""
    result = stage(home, overrides=override, check=False)
    assert result.returncode == 0, (
        "stage_docker_deploy aborted after a successful deploy because the "
        "cosmetic address lookup failed:\n" + result.stdout + result.stderr
    )


@pytest.mark.parametrize(
    "override", [IP_UNREACHABLE, IP_MISSING], ids=["no-route", "no-iproute2"]
)
def test_the_access_urls_are_printed_even_when_the_address_is_unknown(home, override):
    """Guards the test above: exit 0 having printed nothing proves nothing.

    Asserted against the summary lines themselves rather than the exit status,
    because the operator's complaint is not "it returned 2", it is "it never
    told me where the thing is". localhost is the documented fallback and is
    correct on the machine the installer just ran on.
    """
    result = stage(home, overrides=override, check=False)
    assert "Access URLs:" in result.stdout, result.stdout + result.stderr
    assert "https://localhost/" in result.stdout, result.stdout
    assert "Install directory:" in result.stdout, result.stdout
    assert "docker compose logs -f" in result.stdout, result.stdout


def test_a_working_ip_command_still_supplies_the_real_address(home):
    """The control: the fallback must not have replaced the lookup.

    HARNESS's `ip` stub prints a routing line whose `src` is 10.0.0.2. If the
    fix had been to drop the lookup and always print localhost, every assertion
    above would still pass and the summary would have become useless on every
    host that has more than a loopback.
    """
    result = stage(home)
    assert "https://10.0.0.2/" in result.stdout, result.stdout
    assert "localhost" not in result.stdout, result.stdout


# --------------------------------------------------------------------------
# The same bare-assignment mechanism, twice more, where a crafted message dies
# with it.
# --------------------------------------------------------------------------
#
# `host_ip=$(... | ...)` above is one instance of a shape that appears more than
# once in install.sh: a bare assignment of a *pipeline* under
# `set -euo pipefail`. pipefail promotes the left-hand command's non-zero status
# past the right-hand one that returned a clean 0, the assignment is its own
# simple command, and errexit ends the installer on that line -- before the
# `if [[ -z ... ]]; then cb_fail ...` written directly underneath for exactly
# that case ever runs. The operator gets a silent non-zero exit instead of the
# sentence somebody wrote to explain it.
#
# These two run the shipped functions with the failing command stubbed out and
# assert on the message, not the exit status: both spellings exit non-zero, and
# the exit status is not the thing that was lost.


def _run_function(
    name: str, home: Path, *, overrides: str = "", args: tuple[str, ...] = ()
) -> subprocess.CompletedProcess:
    """Run one shipped install.sh function against the stub harness.

    Same construction as stage() -- the harness first, then the caller's
    overrides, then the real function body pulled out of install.sh, which
    redefines any same-named stub the harness set up.

    `args` are passed to the function itself. A bash function has its own
    positional parameters, so a `set --` in `overrides` sets the *script's* and
    leaves `$1` unset inside the function -- which under `set -u` aborts with
    "unbound variable" before reaching anything under test.
    """
    call = " ".join([name, *(shlex.quote(a) for a in args)])
    script = "\n".join([HARNESS, overrides, _extract(name), call])
    env = dict(os.environ, SANDBOX_HOME=str(home))
    return subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, env=env
    )


# glibc's getent exits 2 for a key it cannot resolve -- an account that is not
# in passwd at all, or one that lives in an NSS source (LDAP, SSSD) that is not
# answering. It prints nothing in that case, exactly like this stub.
GETENT_UNKNOWN_USER = """
getent() { return 2; }
docker_target_user() { echo "ghost"; }
cb_fail() { echo "FAIL: $1 -- $2"; exit 1; }
"""


def test_an_unresolvable_user_gets_the_message_written_for_it(home):
    """docker_target_home has a cb_fail for this and it has to be reachable.

    `user_home="$(getent passwd "${target_user}" | cut -d: -f6)"` as a bare
    assignment dies on the spot when getent exits 2: `cut` returns 0, pipefail
    promotes the 2, errexit ends the run, and "Failed to resolve user home"
    two lines below is dead code. The operator installing over sudo from an
    LDAP account that NSS cannot resolve gets an exit 2 and no explanation of
    which user was not found or what to do about it.
    """
    result = _run_function("docker_target_home", home, overrides=GETENT_UNKNOWN_USER)
    assert "Failed to resolve user home" in result.stdout, (
        "the installer died on the getent line instead of reporting it:\n"
        f"exit={result.returncode}\n{result.stdout}{result.stderr}"
    )
    assert "ghost" in result.stdout, (
        "the failure does not name the user that could not be resolved, which "
        f"is the only actionable part of it:\n{result.stdout}"
    )


def test_a_resolvable_user_still_gets_its_real_home(home):
    """The control: `|| true` must not have turned every lookup into a failure.

    A fix that swallowed the output as well as the status would satisfy the
    test above and hand every Docker install /root or an empty path.
    """
    overrides = f"""
getent() {{ echo "ghost:x:1000:1000:Ghost:{home}/ghost:/bin/bash"; }}
docker_target_user() {{ echo "ghost"; }}
"""
    result = _run_function("docker_target_home", home, overrides=overrides)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == f"{home}/ghost", (
        f"docker_target_home no longer returns the user's home:\n{result.stdout!r}"
    )


# jq exits 2 on input it cannot parse -- a truncated or proxy-mangled response
# body that still arrived with a 200, which is what `curl -fsSL` hands back.
JQ_UNPARSEABLE = """
jq() { echo "parse error: Invalid numeric literal" >&2; return 2; }
"""


def test_an_unparseable_release_refuses_to_install_out_loud(home):
    """Checksum verification must fail *with its reason*, not just fail.

    `checksum_url=$(echo "$release_json" | jq -r ...)` is the same bare
    assignment: `echo` cannot fail, so the pipeline's status is jq's, pipefail
    surfaces it and errexit ends the install. The install stopping is correct
    here -- this function is deliberately fail-closed -- but the operator is
    left to guess whether an unverifiable bundle was rejected or the installer
    simply crashed, and the message below the assignment says which.
    """
    result = _run_function(
        "cb_verify_bundle_checksum",
        home,
        overrides=JQ_UNPARSEABLE + "\nCB_VERSION=1.2.3\nSKIP_CHECKSUM=false\n",
        args=("{}", "bundle.tar.gz"),
    )
    assert result.returncode != 0, (
        "an unverifiable bundle was accepted:\n" + result.stdout + result.stderr
    )
    assert "SHA256SUMS" in result.stdout, (
        "the install stopped without saying that the bundle could not be "
        f"verified:\n exit={result.returncode}\n{result.stdout}{result.stderr}"
    )
