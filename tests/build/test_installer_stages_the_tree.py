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


def test_activation_keeps_a_rollback_copy_until_health() -> None:
    activate = _function(SETUP, "cb_activate_runtime_tree")
    assert "python.prev" in activate and "circuit-breaker.prev" in activate
    finalise = _function(SETUP, "cb_finalise_runtime_tree")
    assert "rm -rf" in finalise and "python.prev" in finalise and "_MEI" in finalise


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
