"""`--airgap` has to mean what it says.

CLAUDE.md makes air-gap a first-class deployment, not a courtesy: "`CB_AIRGAP=true`
must block outbound calls. No feature may assume internet access." An installer
that mostly honours that is worse than one that never claimed it — the operator
on an isolated network has no way to see the request that was made, only an
install that fails somewhere strange, or worse, one that succeeds because the
host was not as isolated as they believed.

So these tests do not check that air-gap mode is *documented*. They check that
every command in the installer capable of leaving this host is either
unreachable in air-gap mode or is preceded by a guard, and that the two ways an
operator asks for air-gap (`--airgap`, `CB_AIRGAP=true`) reach the same code.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALLER = REPO_ROOT / "install.sh"
SETUP = REPO_ROOT / "deploy" / "setup.sh"
ENV_TEMPLATE = REPO_ROOT / "deploy" / "misc" / ".env.template"

# Commands that can put a packet on the wire. Package managers count: on an
# isolated host `apt-get install` is an outbound request that happens to fail
# slowly.
OUTBOUND = re.compile(
    r"""(?x)(?<![\w-])(
        curl\s+-|wget\s+-|wget\s+http|docker\s+pull|dig\s+\+|
        apt-get\s+(?:install|update)|\$\{?PKG_MGR\}?\s+(?:install|update)|
        dnf\s+(?:install|config-manager)|pacman\s+-S|apk\s+add|
        add-apt-repository|rpm\s+--import
    )"""
)
DOUBLE_QUOTED = re.compile(r'"[^"]*"')

# Functions whose outbound calls need no in-function guard, each with the reason
# air-gap mode can never reach them. Anything not listed here must guard itself;
# a new entry is a claim that has to be true, not a way to silence the test.
UNREACHABLE_IN_AIRGAP = {
    "install.sh": {
        "cb_install_docker_if_missing": (
            "compose-only path, reached solely from stage_docker_deploy; "
            "--airgap --docker is rejected during argument parsing"
        ),
        "stage_docker_deploy": (
            "--docker deployment; rejected in combination with --airgap"
        ),
        "cb_verify_bundle_checksum": (
            "only called on the download branch of stage0_download_bundle, and "
            "--airgap requires --local-bundle, which takes the other branch"
        ),
        "stage0_download_bundle": (
            "every fetch here is inside the `else` of the --local-bundle check, "
            "and --airgap requires --local-bundle"
        ),
    },
    "deploy/setup.sh": {
        "stage8_start_services": (
            "the only curl is a health poll of http://127.0.0.1:8000 — loopback "
            "never leaves the host"
        ),
        "cb_try_install_docker_ce": (
            "helper with no guard of its own; both call sites (stage2_dependencies, "
            "run_upgrade) are air-gap guarded, which the guard test below checks"
        ),
    },
}


def _script_text(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def _outbound_sites(rel: str) -> dict[str, int]:
    """First outbound-capable line in each top-level function of a shell script.

    String literals are blanked before matching so that advice printed to the
    operator ("Check internet: curl -I https://github.com") is not mistaken for
    a request the installer makes itself.
    """
    sites: dict[str, int] = {}
    current: str | None = None
    for lineno, raw in enumerate(_script_text(rel).splitlines(), start=1):
        opened = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\(\)\s*\{", raw)
        if opened:
            current = opened.group(1)
        elif raw == "}":
            current = None
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if OUTBOUND.search(DOUBLE_QUOTED.sub('""', stripped)):
            name = current or "<top level>"
            sites.setdefault(name, lineno)
    return sites


def _function_start(rel: str, name: str) -> int:
    match = re.search(rf"^{re.escape(name)}\(\)\s*\{{", _script_text(rel), re.MULTILINE)
    assert match, f"{rel} no longer defines {name}()"
    return _script_text(rel)[: match.start()].count("\n") + 1


def _run_installer(args: list[str], env_extra: dict[str, str] | None = None):
    """Run install.sh far enough to hit the argument-parsing guards.

    Safe to execute: the guards sit above main(), so nothing is created, and the
    process is not root in any case.
    """
    env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LC_ALL": "C", "TERM": "dumb"}
    env.update(env_extra or {})
    return subprocess.run(
        ["bash", str(INSTALLER), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
        timeout=60,
    )


def test_every_outbound_command_is_guarded_or_unreachable_in_airgap():
    """The load-bearing test: no function may reach the network in air-gap mode
    without either checking CB_AIRGAP first or being provably unreachable."""
    for rel in ("install.sh", "deploy/setup.sh"):
        text = _script_text(rel).splitlines()
        exempt = UNREACHABLE_IN_AIRGAP[rel]
        for func, outbound_line in _outbound_sites(rel).items():
            if func in exempt:
                continue
            assert func != "<top level>", (
                f"{rel}:{outbound_line}: an outbound command runs at the top level, "
                f"before any air-gap decision can be made."
            )
            start = _function_start(rel, func)
            body_before = "\n".join(text[start - 1 : outbound_line - 1])
            assert "CB_AIRGAP" in body_before, (
                f"{rel}:{outbound_line}: {func}() reaches the network before it "
                f"ever looks at CB_AIRGAP. In air-gap mode this is a request the "
                f"operator was promised would not happen. Either guard it "
                f"(`if [[ \"${{CB_AIRGAP:-false}}\" == \"true\" ]]`) or, if the "
                f"function genuinely cannot run in air-gap mode, add it to "
                f"UNREACHABLE_IN_AIRGAP with the reason."
            )


def test_airgap_refuses_to_start_without_a_local_bundle():
    """Resolving a release from the GitHub API is an outbound request, so air-gap
    has nothing to install unless the tarball is already on the host — and the
    operator must learn that before a user, a directory tree and a set of
    secrets exist."""
    result = _run_installer(["--airgap"])
    assert result.returncode == 1, (
        f"`install.sh --airgap` with no bundle exited {result.returncode}; it must "
        f"stop, because the only way to obtain a bundle is a download air-gap "
        f"mode forbids.\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "--local-bundle" in result.stderr, (
        f"The refusal must name the flag that fixes it. Got: {result.stderr!r}"
    )


def test_the_environment_variable_and_the_flag_are_the_same_switch():
    """CLAUDE.md specifies CB_AIRGAP=true as the contract; the flag is a
    convenience. If only the flag were wired up, `CB_AIRGAP=true bash install.sh`
    would silently perform a normal networked install."""
    result = _run_installer([], env_extra={"CB_AIRGAP": "true"})
    assert result.returncode == 1 and "--local-bundle" in result.stderr, (
        "CB_AIRGAP=true in the environment did not enable air-gap mode — the "
        "installer got past the guard that --airgap trips.\n"
        f"exit={result.returncode} stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_airgap_refuses_the_compose_deployment_rather_than_faking_it():
    """--docker fetches the compose files over HTTP and pulls images from ghcr.io.
    There is no offline version of that path, so combining the flags has to be an
    error; running it and calling the result air-gapped would be the lie."""
    result = _run_installer(["--airgap", "--docker", "--local-bundle", "/nonexistent.tgz"])
    assert result.returncode == 1, (
        f"--airgap --docker exited {result.returncode}. Compose deployment cannot "
        f"be performed without pulling images, so it must be refused up front."
    )
    assert "--docker" in result.stderr


def test_the_dependency_gate_reports_everything_missing_in_one_pass():
    """An offline operator cannot re-run and let apt sort it out: each missing
    package is a trip to the media cupboard. Reporting them one at a time turns
    one round trip into a dozen, so the gate collects the whole list first."""
    body = re.search(
        r"^cb_airgap_verify_dependencies\(\) \{\n(.*?)^\}$",
        SETUP.read_text(encoding="utf-8"),
        re.DOTALL | re.MULTILINE,
    )
    assert body, "deploy/setup.sh no longer defines cb_airgap_verify_dependencies()"

    harness = "\n".join(
        [
            "set -uo pipefail",
            "cb_section() { :; }",
            "cb_step() { :; }",
            "cb_ok() { echo \"OK: $1\"; }",
            "cb_warn() { echo \"WARN: $1\"; }",
            "cb_fail() { echo \"FAIL: $1\"; exit 1; }",
            "cb_airgap_find_pg_bin_dir() { return 1; }",
            body.group(1),
            "cb_airgap_verify_dependencies",
        ]
    )
    # An empty PATH makes every dependency missing at once, which is precisely
    # the case that must produce one list rather than one failure.
    bash = shutil.which("bash") or "/bin/bash"
    result = subprocess.run(
        [bash, "-c", harness],
        capture_output=True,
        text=True,
        env={"PATH": "", "LC_ALL": "C"},
        timeout=60,
    )

    assert result.returncode == 1, (
        f"With nothing installed, the air-gap gate must stop the install. "
        f"exit={result.returncode}\n{result.stdout}\n{result.stderr}"
    )
    for expected in ("nats-server", "postgresql-15", "pgbouncer", "redis-server", "nginx"):
        assert expected in result.stdout, (
            f"{expected!r} is missing from the air-gap dependency report, so the "
            f"operator would stage everything else and fail again on this one.\n"
            f"{result.stdout}"
        )
    assert "circuit-breaker-nats" in result.stdout, (
        "nats-server has no distro package on Ubuntu 22.04 or Fedora. The report "
        "must name the circuit-breaker-nats companion package published beside "
        "the release tarball, or the operator has nothing to go and fetch."
    )
    assert result.stdout.count("FAIL:") == 1, (
        "The gate must fail once, after listing everything.\n" + result.stdout
    )


def test_the_installed_env_records_which_mode_the_host_was_installed_in():
    """The backend reads CB_AIRGAP to block its own outbound calls. If the
    installer never writes it, an air-gapped install produces an application
    that still believes it is online."""
    assert "CB_AIRGAP=${CB_AIRGAP}" in ENV_TEMPLATE.read_text(encoding="utf-8"), (
        "deploy/misc/.env.template must carry CB_AIRGAP=${CB_AIRGAP}: the flag "
        "governs the installer, but the running application reads the .env."
    )
    assert "CB_AIRGAP=${CB_AIRGAP}" in SETUP.read_text(encoding="utf-8"), (
        "setup.sh's fallback .env writer (used when the template is missing) "
        "must emit CB_AIRGAP too, or the fallback quietly produces a networked "
        "install on an isolated host."
    )


def test_help_describes_the_promise_and_its_precondition():
    """Air-gap is only usable if the operator knows to stage a bundle first."""
    help_text = _run_installer(["--help"]).stdout
    assert "--airgap" in help_text, "--airgap is undocumented in --help"
    airgap_block = help_text[help_text.index("--airgap") :]
    airgap_block = airgap_block[: airgap_block.index("--help")]
    assert "--local-bundle" in airgap_block, (
        "The help must state that --airgap requires --local-bundle, or the "
        "operator discovers it only after copying the installer to the isolated "
        "host.\n" + airgap_block
    )
    assert "CB_AIRGAP" in airgap_block, (
        "The help must mention the CB_AIRGAP environment variable, which is the "
        "form CLAUDE.md specifies and the form automation will use."
    )
