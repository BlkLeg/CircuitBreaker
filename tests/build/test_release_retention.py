"""Run native retention functions over temporary releases and fake host tools."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def run(tmp_path, commands, *, backup_fails=False, health_version="0.4.7"):
    current = tmp_path / "current"
    (current / "share").mkdir(parents=True)
    (current / "share/VERSION").write_text("0.4.7")
    (current / "old-marker").write_text("old")
    backup = tmp_path / "snapshot.tar.gz"
    library = (ROOT / "deploy/lib/release-retention.sh").read_text()
    library = library.replace("/etc/circuitbreaker", str(tmp_path / "config"))
    library = library.replace("/opt/circuitbreaker.previous", str(tmp_path / "previous"))
    library = library.replace("/opt/circuitbreaker.retained", str(tmp_path / "retained"))
    library = library.replace("/opt/circuitbreaker.failed", str(tmp_path / "failed"))
    library = library.replace("/opt/circuitbreaker", str(current))
    library = library.replace("/usr/local/bin/cb backup", "fake_backup")
    harness = f'''set -euo pipefail
_cb_lifecycle_trusted_program() {{ [[ -f "$1" && ! -L "$1" ]]; }}
systemctl() {{ printf '%s\\n' "$*" >> '{tmp_path}/units'; }}
sleep() {{ :; }}
curl() {{ if [[ "${{@: -1}}" == */health ]]; then printf '%s' '{{"version":"{health_version}"}}'; fi; }}
fake_backup() {{ {'return 1' if backup_fails else f"printf snapshot > '{backup}'; printf '%s\\n' '{backup}' >&4"}; }}
UPGRADE_MODE=true
{library}
{commands}
'''
    return subprocess.run(["bash", "-c", harness], text=True, capture_output=True)


def test_failed_backup_never_moves_release_or_stops_writers(tmp_path):
    result = run(tmp_path, "cb_release_prepare", backup_fails=True)
    assert result.returncode == 7
    assert (tmp_path / "current/old-marker").exists()
    assert not (tmp_path / "previous").exists()
    assert not (tmp_path / "units").exists()


def test_successful_backup_precedes_stop_and_retains_whole_release(tmp_path):
    result = run(tmp_path, "cb_release_prepare")
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "current").exists()
    assert (tmp_path / "previous/old-marker").read_text() == "old"
    reference = tmp_path / "previous/.cb-backup-reference"
    assert reference.read_text().strip() == str(tmp_path / "snapshot.tar.gz")
    assert reference.stat().st_mode & 0o777 == 0o600
    units = (tmp_path / "units").read_text()
    assert "circuitbreaker-worker@monitor_probe_dispatch" in units
    assert "stop circuitbreaker-backend" in units


def test_failed_activation_restores_release_and_reports_manual_data_restore(tmp_path):
    result = run(tmp_path, '''cb_release_prepare
mkdir -p "''' + str(tmp_path / "current/share") + '''"
printf 0.4.8 > "''' + str(tmp_path / "current/share/VERSION") + '''"
cb_release_revert_failed
''')
    assert result.returncode == 8, result.stderr
    assert (tmp_path / "current/old-marker").exists()
    assert "sudo cb restore" in result.stderr
    assert list(tmp_path.glob("failed.*"))


def test_restored_release_with_unhealthy_version_requires_manual_recovery(tmp_path):
    result = run(tmp_path, "cb_release_prepare\ncb_release_revert_failed", health_version="0.4.8")
    assert result.returncode == 9
    assert (tmp_path / "current/old-marker").exists()


def test_release_recovery_restores_the_previous_install_identity(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    identity = config / "install-identity.json"
    identity.write_text('{"version":"0.4.7","mode":"native"}')
    result = run(tmp_path, "cb_release_prepare\nprintf '%s' '{\"version\":\"0.4.8\",\"mode\":\"native\"}' > " + str(identity) + "\ncb_release_revert_failed")
    assert result.returncode == 8, result.stderr
    assert identity.read_text() == '{"version":"0.4.7","mode":"native"}'
    assert identity.stat().st_mode & 0o777 == 0o644
