"""install.sh stages the runtime tree and setup.sh activates it only after services stop."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INSTALL = (ROOT / "install.sh").read_text(encoding="utf-8")
SETUP = (ROOT / "deploy" / "setup.sh").read_text(encoding="utf-8")
UNINSTALL = (ROOT / "uninstall.sh").read_text(encoding="utf-8")


def _function(source: str, name: str) -> str:
    match = re.search(rf"^{name}\(\) \{{\n(.*?)^\}}", source, re.M | re.S)
    assert match, f"{name} not found"
    return match.group(1)


def test_install_checks_for_the_tree_not_a_root_binary() -> None:
    body = _function(INSTALL, "stage0_download_bundle")
    assert '"${CB_BUNDLE_DIR}/bin/circuit-breaker"' in body
    assert '"${CB_BUNDLE_DIR}/python/bin/python3"' in body
    # PyInstaller onefile stays installable for the upgrade journey until Task 8.
    assert '"${CB_BUNDLE_DIR}/circuit-breaker"' in body


def test_install_stages_rather_than_overwrites_the_runtime() -> None:
    body = _function(INSTALL, "stage0_install_bundle")
    assert "/opt/circuitbreaker/.staging" in body
    # PBS stages; the PyInstaller branch still copies the root binary so
    # --previous can establish a pre-PBS host.
    assert "cp -f \"${CB_BUNDLE_DIR}/circuit-breaker\" /opt/circuitbreaker/bin/circuit-breaker" in body
    assert "/opt/circuitbreaker/python" not in body.replace("/opt/circuitbreaker/.staging", ""), (
        "the live python/ directory is only ever touched by cb_activate_runtime_tree, after services stop"
    )


def test_setup_activates_after_stop_and_finalises_after_readyz() -> None:
    assert "cb_activate_runtime_tree() {" in SETUP and "cb_finalise_runtime_tree() {" in SETUP
    assert "cb_activate_runtime_tree" in _function(SETUP, "stage6_apply_binary")
    start = _function(SETUP, "stage8_start_services")
    assert "/api/v1/readyz" in start
    assert start.index("/api/v1/readyz") < start.index("cb_finalise_runtime_tree")
    upgrade = _function(SETUP, "run_upgrade")
    assert upgrade.index("systemctl stop circuitbreaker.target") < upgrade.index("stage6_apply_binary")
    # `systemctl stop circuitbreaker.target` alone does not stop a unit that
    # was pulled in with Wants= (a start-time-only dependency) rather than
    # PartOf= — confirmed live, where circuitbreaker-backend kept running,
    # unchanged, through a "stopped" target while its runtime tree was
    # replaced underneath it. Every backing service this upgrade is about to
    # swap files under must therefore also be named explicitly here, so the
    # stop works regardless of whether the *currently installed* unit files
    # (which may predate any circuitbreaker.target-level fix) carry PartOf=.
    stop_step = upgrade[: upgrade.index("stage6_apply_binary")]
    for unit in (
        "circuitbreaker-backend",
        "circuitbreaker-pgbouncer",
        "circuitbreaker-redis",
        "circuitbreaker-nats",
        "circuitbreaker-postgres",
    ):
        assert unit in stop_step, f"run_upgrade's stop step does not name {unit} explicitly"


def test_target_member_units_propagate_a_target_stop() -> None:
    """Wants= only pulls a unit in at start; PartOf= is what makes
    `systemctl stop/restart circuitbreaker.target` (run_upgrade, the
    installer journey, and the "Manual start" hint install.sh prints on
    failure) actually stop the unit too. Confirmed live: without PartOf=,
    circuitbreaker-backend survived a target stop untouched while its files
    were swapped underneath it — every CB-owned service the target lists
    must carry it, matching the precedent circuitbreaker-worker@.service
    already set.
    """
    target = (ROOT / "deploy" / "systemd" / "circuitbreaker.target").read_text(encoding="utf-8")
    # Only CB-owned `.service` entries: this excludes nginx.service (a system
    # package unit we ship no file for) and circuitbreaker-healthcheck.timer
    # (a .timer, not a .service — it already cascades via its own
    # Requires=circuitbreaker-backend.service rather than needing PartOf=).
    owned_services = set(re.findall(r"^Wants=(circuitbreaker-[\w@.]+)\.service$", target, re.M))
    assert owned_services, "expected at least the backend and worker units in circuitbreaker.target's Wants="
    for name in owned_services:
        unit_file = "circuitbreaker-worker@.service" if name.startswith("circuitbreaker-worker@") else f"{name}.service"
        path = ROOT / "deploy" / "systemd" / unit_file
        body = path.read_text(encoding="utf-8")
        assert "PartOf=circuitbreaker.target" in body, f"{unit_file} is a member of circuitbreaker.target but lacks PartOf=circuitbreaker.target"


def test_activation_keeps_a_rollback_copy_until_health() -> None:
    activate = _function(SETUP, "cb_activate_runtime_tree")
    assert "python.prev" in activate and "circuit-breaker.prev" in activate
    finalise = _function(SETUP, "cb_finalise_runtime_tree")
    assert "rm -rf" in finalise and "python.prev" in finalise and "_MEI" in finalise


def test_rollback_drops_failed_pbs_tree_when_python_prev_absent() -> None:
    """PyInstaller → PBS: no prior tree, so rollback must remove the failed activation."""
    body = _function(SETUP, "cb_rollback_runtime_tree")
    assert "python.prev" in body
    # else branch (no python.prev): drop activated tree and PBS-only cb-python.
    assert re.search(
        r"else\s*\n\s*rm -rf /opt/circuitbreaker/python\s*\n\s*rm -f /opt/circuitbreaker/bin/cb-python",
        body,
    ), body
    assert "circuit-breaker.prev" in body


def test_identity_records_the_runtime() -> None:
    body = _function(SETUP, "stage9_write_install_identity")
    assert "runtime=pbs" in body or 'runtime="$runtime"' in body
    assert "runtime=pyinstaller" in body or 'runtime="$runtime"' in body
    assert "/opt/circuitbreaker/python/bin/python3" in body


def test_channel_flag_exists_and_defaults_to_stable() -> None:
    assert re.search(r'^CB_CHANNEL="\$\{CB_CHANNEL:-stable\}"', INSTALL, re.M)
    assert "--channel)" in INSTALL
    assert "--channel stable|candidate" in INSTALL


def test_uninstall_reads_the_identity_before_guessing() -> None:
    assert "cb_find_install_identity" in UNINSTALL
    assert "if [ -d /opt/circuitbreaker ] || [ -f /etc/systemd/system/circuitbreaker-backend.service ]" not in UNINSTALL
    assert "/opt/circuitbreaker/python" in UNINSTALL


def test_pick_release_honours_the_channel() -> None:
    """Behavioural: stable skips prereleases, candidate takes the newest of either."""
    if subprocess.run(["jq", "--version"], capture_output=True, check=False).returncode != 0:
        import pytest
        pytest.skip("jq is not installed")
    body = re.search(r"^cb_pick_release\(\) \{.*?^\}", INSTALL, re.M | re.S).group(0)
    releases = '[{"tag_name":"v1.0.1-rc.1","draft":false,"prerelease":true},{"tag_name":"v1.0.0","draft":false,"prerelease":false}]'
    for channel, expected in (("stable", "v1.0.0"), ("candidate", "v1.0.1-rc.1")):
        out = subprocess.run(["bash", "-c", f'{body}\nCB_CHANNEL={channel} cb_pick_release | jq -r .tag_name'],
                             input=releases, capture_output=True, text=True, check=True).stdout.strip()
        assert out == expected, (channel, out)
