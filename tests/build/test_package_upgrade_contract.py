# tests/build/test_package_upgrade_contract.py
"""The deb/rpm packages must be able to upgrade, and to be rolled back.

docs/release/1.0.0-compatibility-policy.md defines rollback as "restoring the
complete pre-upgrade backup", and docs/installation/upgrading.md tells the
operator that the upgrade takes that backup itself. Both were true only of the
install.sh path, where deploy/setup.sh's run_upgrade does the work. The package
path had no preinstall hook at all and did not ship restore.sh, so
`dnf upgrade circuit-breaker` migrated the schema with nothing to go back to and
no tool to go back with -- a documented recovery procedure that could not be
performed. ADR 0005 Phase 3 is what found it, because it is the first thing in
this project's history to upgrade a packaged install and then look.

Where these tests can run the scriptlets they do, rather than grepping them.
A scriptlet is a decision tree over three packagers' argument conventions, and
the way that goes wrong is a branch taken for the wrong convention -- which a
substring assertion cannot see and an execution can.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGING = REPO_ROOT / "packaging"
NFPM = REPO_ROOT / "nfpm.yaml"
PREINSTALL = PACKAGING / "preinstall.sh"
PREREMOVE = PACKAGING / "preremove.sh"
POSTINSTALL = PACKAGING / "postinstall.sh"
ROLLBACK = PACKAGING / "rollback.sh"
RESTORE = REPO_ROOT / "deploy" / "scripts" / "restore.sh"

# The three packagers nfpm emits for, and what each passes to a scriptlet when
# the transaction is an upgrade rather than a first install.
#
#   dpkg  preinst  "upgrade <old-version>"      prerm  "upgrade <new-version>"
#   rpm   %pre     the count after the txn: 2   %preun the count remaining: 1
#   apk   .pre-install runs on install only; apk uses a separate .pre-upgrade
#         script that nfpm does not emit, which is why apk is a tier 3 format
#         and not a tier 1 one.
UPGRADE_ARGS_PREINSTALL = [["upgrade", "1.2.3"], ["2"]]
INSTALL_ARGS_PREINSTALL = [["install"], ["1"], []]
UPGRADE_ARGS_PREREMOVE = [["upgrade", "1.2.3"], ["1"]]
REMOVE_ARGS_PREREMOVE = [["remove"], ["0"]]


def _run(script: Path, args: list[str], env: dict[str, str], cwd: Path):
    return subprocess.run(
        ["bash", str(script), *args],
        env={**os.environ, **env},
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def _stub(directory: Path, name: str, body: str) -> Path:
    """Write an executable stub onto a directory destined for PATH."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(f"#!/bin/bash\n{body}\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


@pytest.fixture
def layout(tmp_path: Path):
    """A fixture install: an env file, a data dir, and a stub PATH."""
    data_dir = tmp_path / "data"
    (data_dir / "backups").mkdir(parents=True)
    env_file = tmp_path / "circuit-breaker.env"
    env_file.write_text(
        "CB_DB_URL=postgresql://circuitbreaker:changeme@127.0.0.1:5432/circuitbreaker\n"
        f"CB_DATA_DIR={data_dir}\n",
        encoding="utf-8",
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    env = {
        "CB_ENV_FILE": str(env_file),
        # A user that does not exist, so the chown guard is exercised without
        # needing root or a real service account on the test host.
        "CB_SERVICE_USER": "cb-nonexistent-test-user",
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
    }
    return {"tmp": tmp_path, "data_dir": data_dir, "env_file": env_file, "bin": bin_dir, "env": env}


# ── the hooks are wired at all ──────────────────────────────────────────────


def test_nfpm_declares_all_three_scriptlets():
    text = NFPM.read_text(encoding="utf-8")
    scripts = re.search(r"^scripts:\n((?:[ \t]+.*\n|\s*#.*\n)+)", text, re.M)
    assert scripts, "nfpm.yaml has no scripts: block"
    body = scripts.group(1)
    for hook, script in (
        ("preinstall", "packaging/preinstall.sh"),
        ("postinstall", "packaging/postinstall.sh"),
        ("preremove", "packaging/preremove.sh"),
    ):
        assert re.search(rf"^\s*{hook}:\s*{re.escape(script)}\s*$", body, re.M), (
            f"nfpm.yaml does not wire {hook} to {script}"
        )


@pytest.mark.parametrize("script", [PREINSTALL, PREREMOVE, POSTINSTALL, ROLLBACK])
def test_scriptlets_exist_and_are_executable(script: Path):
    assert script.is_file(), f"{script} is missing"
    assert script.stat().st_mode & 0o111, f"{script} is not executable"


# ── preinstall: the pre-upgrade backup gate ────────────────────────────────


@pytest.mark.parametrize("args", INSTALL_ARGS_PREINSTALL, ids=lambda a: " ".join(a) or "no-args")
def test_preinstall_does_nothing_on_a_fresh_install(args, layout):
    """A first install has no database to dump. Dumping one would either fail or,
    worse, back up somebody else's."""
    result = _run(PREINSTALL, args, layout["env"], layout["tmp"])
    assert result.returncode == 0, result.stderr
    assert "upgrade detected" not in result.stdout.lower(), (
        f"install arguments {args!r} were read as an upgrade:\n{result.stdout}"
    )


@pytest.mark.parametrize("args", UPGRADE_ARGS_PREINSTALL, ids=lambda a: " ".join(a))
def test_preinstall_detects_an_upgrade_for_dpkg_and_rpm(args, layout):
    """The detection itself, independent of whether a backup can be taken. The
    database is unreachable here, so the run exits cleanly after announcing what
    it is -- which is exactly the branch under test."""
    result = _run(PREINSTALL, args, layout["env"], layout["tmp"])
    assert result.returncode == 0, result.stderr
    assert "upgrade detected" in result.stdout.lower(), (
        f"upgrade arguments {args!r} were not recognised:\n{result.stdout}{result.stderr}"
    )


def test_preinstall_skips_cleanly_when_there_is_no_env_file(layout):
    """An upgrade over an install that never generated its environment. There is
    no connection string to dump with and no schema this package ever migrated,
    so this is not a backup failure and must not block the upgrade."""
    env = {**layout["env"], "CB_ENV_FILE": str(layout["tmp"] / "absent.env")}
    result = _run(PREINSTALL, ["2"], env, layout["tmp"])
    assert result.returncode == 0, result.stderr
    assert "nothing to back up" in result.stdout.lower()


def test_preinstall_skips_when_the_database_is_unreachable(layout):
    """Unreachable is not the same as failed. An operator upgrading a host whose
    database lives elsewhere and is down has no data at risk from the
    transaction, and refusing would strand them."""
    _stub(layout["bin"], "pg_isready", "exit 1")
    _stub(layout["bin"], "pg_dump", 'echo "pg_dump must not run" >&2; exit 99')
    result = _run(PREINSTALL, ["2"], layout["env"], layout["tmp"])
    assert result.returncode == 0, result.stderr
    assert "not reachable" in result.stdout.lower()
    assert "pg_dump must not run" not in result.stderr


def test_preinstall_refuses_the_upgrade_when_a_reachable_database_cannot_be_dumped(layout):
    """The gate. deploy/setup.sh's run_upgrade fails the upgrade rather than
    warning, for the reason recorded there: it used to print "Backup saved"
    unconditionally over a pg_dump that had exited non-zero, and the documented
    recovery then pointed at a file that was empty or absent."""
    _stub(layout["bin"], "pg_isready", "exit 0")
    _stub(layout["bin"], "pg_dump", 'echo "connection refused" >&2; exit 1')
    result = _run(PREINSTALL, ["2"], layout["env"], layout["tmp"])
    assert result.returncode != 0, (
        "a failed pre-upgrade dump must fail the package transaction, not warn:\n"
        f"{result.stdout}{result.stderr}"
    )
    assert "refusing to upgrade" in result.stderr.lower()
    assert "connection refused" in result.stderr, "pg_dump's own error must reach the operator"


def test_preinstall_leaves_no_zero_byte_backup_behind(layout):
    """A zero-byte file sitting among real dumps reads as a usable backup months
    later, which is worse than having none at all."""
    _stub(layout["bin"], "pg_isready", "exit 0")
    _stub(layout["bin"], "pg_dump", "exit 0")  # succeeds, writes nothing
    result = _run(PREINSTALL, ["2"], layout["env"], layout["tmp"])
    assert result.returncode != 0, "an empty dump is a failed backup"
    leftovers = sorted((layout["data_dir"] / "backups").glob("pre-upgrade-*.sql"))
    assert not leftovers, f"empty backup stub was left on disk: {leftovers}"


def test_preinstall_writes_a_backup_and_names_the_rollback_command(layout):
    """The happy path, and the line an operator reads at 3am. deploy/setup.sh
    prints the consuming command on the same screen for the same reason; on a
    packaged host that command is the shipped wrapper, not the /opt path."""
    _stub(layout["bin"], "pg_isready", "exit 0")
    _stub(layout["bin"], "pg_dump", 'echo "-- a dump"')
    result = _run(PREINSTALL, ["2"], layout["env"], layout["tmp"])
    assert result.returncode == 0, result.stderr

    written = sorted((layout["data_dir"] / "backups").glob("pre-upgrade-*.sql"))
    assert len(written) == 1, f"expected exactly one dump, found {written}"
    assert written[0].read_text(encoding="utf-8").strip() == "-- a dump"
    assert stat.S_IMODE(written[0].stat().st_mode) == 0o600, (
        "a database in a file is readable by its owner only"
    )
    assert "circuit-breaker-rollback" in result.stdout, (
        "the backup is useless if the operator is not told what consumes it"
    )


def test_preinstall_does_not_use_a_predictable_temp_path():
    """It runs as root during a package transaction. A fixed name in a
    world-writable directory is a symlink an unprivileged local user can plant
    before the upgrade runs."""
    text = PREINSTALL.read_text(encoding="utf-8")
    assert "mktemp" in text
    assert not re.search(r"[>\s]/tmp/[\w.-]+", text), (
        "preinstall.sh writes to a fixed /tmp path; use mktemp"
    )


# ── preremove: must not disable the unit during an upgrade ─────────────────


def _systemctl_recorder(bin_dir: Path, log: Path):
    _stub(bin_dir, "systemctl", f'echo "$@" >> {log}\nexit 0')


@pytest.mark.parametrize("args", UPGRADE_ARGS_PREREMOVE, ids=lambda a: " ".join(a))
def test_preremove_leaves_the_unit_alone_on_an_upgrade(args, layout):
    """The regression this pins.

    rpm runs the OLD package's %preun AFTER the NEW package's %post during an
    upgrade, so an unconditional stop+disable here ran last and undid the enable
    postinstall.sh had just performed: every `dnf upgrade circuit-breaker`
    finished with the service stopped AND disabled, and no reboot brought it
    back. Nothing in the pipeline had ever upgraded a packaged service, so
    nothing saw it.
    """
    log = layout["tmp"] / "systemctl.log"
    _systemctl_recorder(layout["bin"], log)
    result = _run(PREREMOVE, args, layout["env"], layout["tmp"])
    assert result.returncode == 0, result.stderr
    assert not log.exists(), (
        f"preremove touched systemd on an upgrade ({args!r}):\n{log.read_text()}"
    )


@pytest.mark.parametrize("args", REMOVE_ARGS_PREREMOVE, ids=lambda a: " ".join(a))
def test_preremove_stops_and_disables_on_a_real_removal(args, layout):
    """The other direction matters just as much: a preremove that no-ops on
    removal leaves a dead unit enabled and failing on every boot."""
    log = layout["tmp"] / "systemctl.log"
    _systemctl_recorder(layout["bin"], log)
    result = _run(PREREMOVE, args, layout["env"], layout["tmp"])
    assert result.returncode == 0, result.stderr
    assert log.exists(), f"preremove did nothing on a removal ({args!r})"
    calls = log.read_text(encoding="utf-8")
    assert "stop circuit-breaker.service" in calls
    assert "disable circuit-breaker.service" in calls


# ── postinstall: the upgrade branch ────────────────────────────────────────
#
# Static, unlike the two above: postinstall.sh creates a system user, writes
# under /var/lib and /etc, and generates secrets. Running it to observe a branch
# would mean running all of that as root on the test host.


def test_postinstall_distinguishes_upgrade_from_install():
    text = POSTINSTALL.read_text(encoding="utf-8")
    assert "IS_UPGRADE" in text, "postinstall.sh does not detect an upgrade at all"
    # dpkg signals an upgrade by passing the old version as $2 to `configure`;
    # rpm signals it with a count of 2 or more.
    assert "configure)" in text and '${2:-}' in text, "the dpkg convention is not handled"
    assert "-ge 2" in text, "the rpm convention is not handled"


def test_postinstall_restarts_a_running_service_on_upgrade():
    """rpm replaces the files underneath a live process and tells systemd
    nothing, so without this the operator sees a successful upgrade and a service
    still serving the previous version."""
    text = POSTINSTALL.read_text(encoding="utf-8")
    assert "try-restart" in text, (
        "postinstall.sh must try-restart on upgrade — and try-restart rather than "
        "restart, so an upgrade cannot start a service the operator had stopped"
    )


def test_postinstall_tells_the_operator_how_to_roll_back():
    text = POSTINSTALL.read_text(encoding="utf-8")
    assert "circuit-breaker-rollback" in text
    assert "downgrade" in text.lower(), (
        "the rollback instructions must include reinstalling the previous package: "
        "the dump carries the old schema and the new binary cannot serve it"
    )


# ── the rollback tooling is actually shipped ───────────────────────────────


def test_nfpm_ships_the_restore_script_and_the_rollback_wrapper():
    """The gap this phase closed. docs/installation/upgrading.md named
    /opt/circuitbreaker/deploy/scripts/restore.sh as the rollback command, which
    is the install.sh layout; a deb/rpm host had no such file because restore.sh
    was in no contents: entry."""
    text = NFPM.read_text(encoding="utf-8")
    assert "deploy/scripts/restore.sh" in text, "the package does not ship restore.sh"
    assert "packaging/rollback.sh" in text, "the package does not ship the rollback wrapper"
    assert "/usr/local/bin/circuit-breaker-rollback" in text, (
        "the rollback wrapper must land on PATH; an operator recovering from a bad "
        "upgrade should not have to know an install path"
    )


def test_rollback_wrapper_supplies_every_layout_variable_restore_needs():
    """restore.sh's defaults are the install.sh layout. Its own header records
    what happened when a package host ran it with those defaults: it stopped a
    unit that does not exist, dropped the database as roles that do not exist,
    wrote the vault key into a file the packaged unit never reads, and reported
    success over an install whose every encrypted column had become unreadable.
    """
    wrapper = ROLLBACK.read_text(encoding="utf-8")
    for variable in ("CB_ENV_FILE", "CB_SERVICE_UNIT", "CB_DB_NAME", "CB_DB_OWNER", "CB_DB_SUPERUSER"):
        assert re.search(rf"^export {variable}=", wrapper, re.M), (
            f"rollback.sh does not export {variable}, so restore.sh falls back to the "
            f"install.sh layout on a packaged host"
        )
    assert "circuit-breaker.service" in wrapper, "the packaged unit name must be supplied"


def test_rollback_wrapper_points_at_the_path_nfpm_installs_restore_to():
    """A wrapper that execs a path the package does not create is a rollback tool
    that fails at the moment it is needed."""
    installed_to = re.search(
        r"-\s*src:\s*deploy/scripts/restore\.sh\s*\n\s*dst:\s*(\S+)",
        NFPM.read_text(encoding="utf-8"),
    )
    assert installed_to, "nfpm.yaml does not install deploy/scripts/restore.sh"
    assert installed_to.group(1) in ROLLBACK.read_text(encoding="utf-8"), (
        f"rollback.sh does not exec {installed_to.group(1)}"
    )


def test_rollback_wrapper_lists_what_it_can_restore_when_given_no_argument(layout, tmp_path):
    """An operator who does not know the filename should not be sent to find one
    under time pressure."""
    backups = layout["data_dir"] / "backups"
    (backups / "pre-upgrade-20260828-120000.sql").write_text("-- dump", encoding="utf-8")
    stub_restore = _stub(tmp_path, "restore-stub.sh", "exit 0")
    env = {**layout["env"], "CB_RESTORE_SCRIPT": str(stub_restore)}
    result = subprocess.run(
        ["bash", str(ROLLBACK)],
        env={**os.environ, **env},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2, result.stderr
    assert "pre-upgrade-20260828-120000.sql" in result.stdout, (
        "the wrapper must list the backups it found:\n" + result.stdout
    )
    assert "reinstall the matching package version" in result.stdout.lower(), (
        "restoring a pre-upgrade dump under the newer binary is the mistake this "
        "warning exists to prevent"
    )


def test_restore_script_still_takes_a_bare_sql_dump():
    """The wrapper hands it a pre-upgrade .sql, not a snapshot tarball. If
    restore.sh ever stops accepting that shape, the package rollback breaks
    silently -- which is the state the tree was in before restore.sh grew the
    case."""
    text = RESTORE.read_text(encoding="utf-8")
    assert re.search(r"\*\.sql\|\*\.sql\.gz\)", text), (
        "restore.sh no longer branches on a bare .sql dump"
    )


@pytest.mark.parametrize("script", [PREINSTALL, PREREMOVE, POSTINSTALL, ROLLBACK])
def test_scriptlets_are_syntactically_valid(script: Path):
    result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, f"{script.name}: {result.stderr}"


# ── the upgrade must not leave the service stopped and disabled ─────────────
#
# ADR 0005 Phase 3, F5. Slice 1 made preremove.sh a no-op when the package is
# being replaced, which fixes upgrades *from* a version that has that fix. It
# cannot fix an upgrade from a version already published, because rpm runs the
# OLD package's %preun:
#
#   1. new %pre   2. unpack   3. new %post (enables)   4. OLD %preun (disables)
#
# Verified against the artifact, not the tree: `rpm -qp --scripts` on the
# published circuit-breaker_0.3.4_amd64.rpm shows a %preun that stops and
# disables with no $1 guard, and every released tag through v1.0.0-rc.4 carries
# it. postinstall.sh's try-restart runs at step 3 and cannot help -- step 4 comes
# after it.
#
# %posttrans is the only scriptlet that runs after the old %preun, so that is
# where the repair goes. It restores the state %pre recorded rather than enabling
# unconditionally, for the same reason postinstall uses try-restart rather than
# restart: an upgrade must not start a service the operator deliberately stopped.

POSTTRANS = PACKAGING / "posttrans.sh"


def test_nfpm_wires_posttrans_under_the_top_level_rpm_key():
    """Placement is the whole test, and a substring search cannot see it.

    %posttrans is RPMScripts, which nfpm exposes only under the TOP-LEVEL `rpm:`
    key. `overrides.rpm.scripts` is the packager-agnostic set -- preinstall,
    postinstall, preremove, postremove -- and nfpm ignores an unrecognised key
    there silently. The first version of this wiring put posttrans under
    overrides.rpm; the file read correctly, this test passed on a substring
    match, and the built rpm contained no posttrans scriptlet at all.

    So this parses the YAML and asserts the structure, and the companion test
    below checks the emitted package rather than the intent.

    deb and apk need no equivalent: dpkg runs the old prerm BEFORE unpack and the
    new postinst last, so postinstall's try-restart is already the final word.
    """
    import yaml

    config = yaml.safe_load(NFPM.read_text(encoding="utf-8"))
    rpm = config.get("rpm") or {}
    scripts = rpm.get("scripts") or {}
    assert scripts.get("posttrans") == "packaging/posttrans.sh", (
        "nfpm.yaml does not wire posttrans under the top-level rpm.scripts key, "
        "so nothing runs after the old package's %preun and every upgrade from a "
        "released version ends with the service stopped and disabled. Found: "
        f"rpm.scripts={scripts!r}"
    )
    overrides_rpm_scripts = (config.get("overrides") or {}).get("rpm", {}).get("scripts")
    assert not (overrides_rpm_scripts or {}).get("posttrans"), (
        "posttrans is declared under overrides.rpm.scripts, where nfpm ignores "
        "it without an error"
    )


def test_the_built_rpm_actually_carries_a_posttrans_scriptlet():
    """The effect, not the intent.

    Skipped rather than failed where the toolchain is absent: this asserts a
    property of a built artifact, and a developer without nfpm or rpm should not
    see a red suite for it. CI installs both via scripts/install-build-deps.sh.
    """
    rpm_bin = shutil.which("rpm")
    if not rpm_bin:
        pytest.skip("rpm is not installed on this host")
    built = sorted((REPO_ROOT / "dist" / "native").glob("circuit-breaker_*_amd64.rpm"))
    if not built:
        pytest.skip("no built rpm in dist/native — run `make build` first")
    out = subprocess.run(
        [rpm_bin, "-qp", "--scripts", str(built[-1])],
        capture_output=True, text=True,
    ).stdout
    assert "posttrans" in out.lower(), (
        f"{built[-1].name} carries no posttrans scriptlet. nfpm accepts the key "
        f"only under the top-level rpm: section and drops it silently anywhere "
        f"else, so this is what distinguishes a wired hook from a written one.\n"
        f"scriptlets present:\n{out}"
    )


def test_posttrans_exists_and_is_executable():
    assert POSTTRANS.is_file(), f"{POSTTRANS} is missing"
    assert POSTTRANS.stat().st_mode & 0o111, f"{POSTTRANS} is not executable"


@pytest.fixture
def unit_state(tmp_path: Path):
    """A systemctl stub that records its calls and answers state queries."""
    bin_dir = tmp_path / "bin"
    calls = tmp_path / "systemctl-calls.log"
    state = tmp_path / "unit-state"
    # is-enabled/is-active answer from files the test controls, so the stub can
    # model "the old %preun already disabled it" without a real systemd.
    _stub(
        bin_dir,
        "systemctl",
        f'echo "$@" >> {calls}\n'
        'case "$1" in\n'
        f'  is-enabled) [ -f {tmp_path}/enabled ] ;;\n'
        f'  is-active)  [ -f {tmp_path}/active ] ;;\n'
        '  *) exit 0 ;;\n'
        'esac\n',
    )
    return {
        "tmp": tmp_path,
        "calls": calls,
        "state": state,
        "env": {
            "CB_UNIT_STATE_FILE": str(state),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
        },
    }


def _set_unit(unit_state, *, enabled: bool, active: bool):
    for name, on in (("enabled", enabled), ("active", active)):
        path = unit_state["tmp"] / name
        if on:
            path.write_text("", encoding="utf-8")
        elif path.exists():
            path.unlink()


@pytest.mark.parametrize("args", UPGRADE_ARGS_PREINSTALL)
def test_preinstall_records_the_unit_state_on_an_upgrade(layout, unit_state, args):
    """%pre runs at step 1, before anything has disturbed the unit, so it is the
    only place the pre-transaction state can still be read."""
    _set_unit(unit_state, enabled=True, active=True)
    env = {**layout["env"], **unit_state["env"]}
    env["PATH"] = f"{unit_state['tmp'] / 'bin'}:{layout['env']['PATH']}"
    _run(PREINSTALL, args, env, layout["tmp"])
    recorded = unit_state["state"]
    assert recorded.is_file(), (
        "preinstall did not record the unit state, so posttrans has nothing to "
        "restore and the upgrade ends with the service disabled"
    )
    body = recorded.read_text(encoding="utf-8")
    assert "enabled=1" in body and "active=1" in body, body


@pytest.mark.parametrize("args", INSTALL_ARGS_PREINSTALL)
def test_preinstall_records_nothing_on_a_fresh_install(layout, unit_state, args):
    """There is no prior state on a first install, and a stale stamp would make
    posttrans act on a decision nobody made."""
    _set_unit(unit_state, enabled=False, active=False)
    env = {**layout["env"], **unit_state["env"]}
    env["PATH"] = f"{unit_state['tmp'] / 'bin'}:{layout['env']['PATH']}"
    _run(PREINSTALL, args, env, layout["tmp"])
    assert not unit_state["state"].exists(), (
        "preinstall recorded a unit state on a fresh install"
    )


def test_posttrans_restores_a_service_the_old_preun_disabled(unit_state):
    """The regression itself: enabled and running before, stopped and disabled
    by the old %preun, restored by posttrans."""
    unit_state["state"].write_text("enabled=1\nactive=1\n", encoding="utf-8")
    _set_unit(unit_state, enabled=False, active=False)  # the old %preun ran
    result = _run(POSTTRANS, ["1"], unit_state["env"], unit_state["tmp"])
    assert result.returncode == 0, result.stderr
    calls = unit_state["calls"].read_text(encoding="utf-8")
    assert "enable" in calls, f"posttrans did not re-enable the unit:\n{calls}"
    assert "start" in calls, f"posttrans did not restart the unit:\n{calls}"


def test_posttrans_does_not_start_a_service_that_was_stopped(unit_state):
    """The safety property. An operator who had stopped the service must not
    find it running after an upgrade -- the same reason postinstall uses
    try-restart rather than restart."""
    unit_state["state"].write_text("enabled=1\nactive=0\n", encoding="utf-8")
    _set_unit(unit_state, enabled=False, active=False)
    result = _run(POSTTRANS, ["1"], unit_state["env"], unit_state["tmp"])
    assert result.returncode == 0, result.stderr
    calls = unit_state["calls"].read_text(encoding="utf-8")
    assert not re.search(r"^start ", calls, re.M), (
        f"posttrans started a service the operator had stopped:\n{calls}"
    )


def test_posttrans_is_a_noop_without_a_recorded_state(unit_state):
    """A fresh install leaves no stamp. posttrans still runs on that
    transaction, and must do nothing."""
    _set_unit(unit_state, enabled=False, active=False)
    result = _run(POSTTRANS, ["1"], unit_state["env"], unit_state["tmp"])
    assert result.returncode == 0, result.stderr
    calls = unit_state["calls"].read_text(encoding="utf-8") if unit_state["calls"].exists() else ""
    assert not re.search(r"^(enable|start) ", calls, re.M), (
        f"posttrans acted with no recorded state:\n{calls}"
    )


def test_posttrans_clears_the_stamp(unit_state):
    """A stamp that outlives its transaction would make the *next* upgrade
    restore a state from the previous one."""
    unit_state["state"].write_text("enabled=1\nactive=1\n", encoding="utf-8")
    _set_unit(unit_state, enabled=False, active=False)
    _run(POSTTRANS, ["1"], unit_state["env"], unit_state["tmp"])
    assert not unit_state["state"].exists(), "posttrans left its stamp behind"


# ── the rollback has to be able to authenticate ─────────────────────────────
#
# ADR 0005 Phase 3, F12. Past the confirmation prompt, the rollback reached the
# database and could not log in:
#
#     Password for user circuitbreaker:
#     psql: error: ... FATAL: password authentication failed for user "circuitbreaker"
#
# The asymmetry that caused it: preinstall.sh hands pg_dump the whole CB_DB_URL
# (`"$PG_DUMP" "$DB_URL"`), and the URL carries the password, so the backup
# authenticates. rollback.sh instead parses the URL into its parts and exports
# CB_DB_NAME, CB_DB_OWNER and CB_DB_SUPERUSER -- every identity except the
# credential. restore.sh has always read `PGPASSWORD="${CB_DB_PASSWORD:-}"`, and
# its own comment says why: pg_hba is md5 for 127.0.0.1 and it connects as the
# owner. Nothing ever set that variable on the package path.
#
# The default the package itself generates uses password auth
# (postgresql://circuitbreaker:...@127.0.0.1:5432/circuitbreaker), so this failed
# on the standard install, not an exotic one.


def _run_rollback(tmp_path: Path, db_url: str):
    """Drive rollback.sh with a stub restore that records the env it was given."""
    env_file = tmp_path / "circuit-breaker.env"
    env_file.write_text(f"CB_DB_URL={db_url}\nCB_DATA_DIR={tmp_path}\n", encoding="utf-8")
    recorded = tmp_path / "restore-env.txt"
    restore = _stub(tmp_path / "bin", "restore-stub.sh", f'env > {recorded}\nexit 0\n')
    backup = tmp_path / "pre-upgrade-20260830-000000.sql"
    backup.write_text("-- dump\n", encoding="utf-8")
    result = _run(
        ROLLBACK,
        [str(backup)],
        {"CB_ENV_FILE": str(env_file), "CB_RESTORE_SCRIPT": str(restore)},
        tmp_path,
    )
    env = {}
    if recorded.exists():
        for line in recorded.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            env[key] = value
    return result, env


def test_the_rollback_passes_the_database_password_through(tmp_path: Path):
    result, env = _run_rollback(
        tmp_path, "postgresql://circuitbreaker:s3cr3t@127.0.0.1:5432/circuitbreaker"
    )
    assert result.returncode == 0, f"rollback.sh failed:\n{result.stderr}"
    assert env.get("CB_DB_PASSWORD") == "s3cr3t", (
        "rollback.sh exports every identity except the credential, so restore.sh "
        "runs psql with an empty PGPASSWORD and the documented rollback fails "
        "with 'password authentication failed' on a default install. "
        f"Got CB_DB_PASSWORD={env.get('CB_DB_PASSWORD')!r}"
    )
    # the identities it already got right must keep working
    assert env.get("CB_DB_OWNER") == "circuitbreaker", env.get("CB_DB_OWNER")
    assert env.get("CB_DB_NAME") == "circuitbreaker", env.get("CB_DB_NAME")


def test_the_rollback_decodes_a_percent_encoded_password(tmp_path: Path):
    """A password containing @ or / MUST be percent-encoded in a URL, so those
    are exactly the passwords that arrive encoded -- and handing psql the raw
    encoded form fails the same way as handing it nothing."""
    _, env = _run_rollback(
        tmp_path, "postgresql://circuitbreaker:p%40ss%2Fword@127.0.0.1:5432/circuitbreaker"
    )
    assert env.get("CB_DB_PASSWORD") == "p@ss/word", (
        f"percent-encoded password not decoded: {env.get('CB_DB_PASSWORD')!r}"
    )


def test_a_url_with_no_password_exports_an_empty_one(tmp_path: Path):
    """Peer or trust auth is legitimate; the variable must be empty, not the
    literal user name or a stray colon."""
    _, env = _run_rollback(tmp_path, "postgresql://circuitbreaker@127.0.0.1:5432/circuitbreaker")
    assert env.get("CB_DB_PASSWORD", "") == "", (
        f"expected an empty password, got {env.get('CB_DB_PASSWORD')!r}"
    )
    assert env.get("CB_DB_OWNER") == "circuitbreaker"
