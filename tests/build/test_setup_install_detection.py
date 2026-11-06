"""Run setup.sh's install-mode detection and PGDG codename check over fake host roots.

A fresh install that stopped part-way leaves /etc/circuitbreaker/.env behind.
Treating that as an upgrade sent the re-run into run_upgrade, whose
pre-upgrade backup then failed against a database that never existed. Only a
completed install (identity, running backend, or .env beside an initialised
database) is an upgrade now; anything else resumes the fresh install.
"""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SETUP = (ROOT / "deploy/setup.sh").read_text()


def _block(start: str, end: str) -> str:
    begin = SETUP.index(start)
    return SETUP[begin:SETUP.index(end, begin) + len(end)]


DETECT = _block("  # Upgrade only over a completed install", "\n  fi\n")
PGDG = _block("    # lsb_release is absent from minimal images",
              "/etc/apt/sources.list.d/pgdg.list\n")


def detect(tmp: Path, *, identity=False, env=False, pg_data=False, backend_active=False):
    etc = tmp / "etc"
    etc.mkdir()
    data = tmp / "data"
    if identity:
        (etc / "install-identity.json").write_text("{}")
    if env:
        (etc / ".env").write_text("CB_VAULT_KEY=x\n")
    if pg_data:
        (data / "postgres").mkdir(parents=True)
        (data / "postgres/PG_VERSION").write_text("15\n")
    block = DETECT.replace("/etc/circuitbreaker", str(etc))
    script = f"""set -euo pipefail
UPGRADE_MODE=false
CB_DATA_DIR='{data}'
cb_ok() {{ printf '%s\\n' "$*"; }}
systemctl() {{ {'return 0' if backend_active else 'return 3'}; }}
{block}
echo "UPGRADE_MODE=$UPGRADE_MODE"
"""
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_a_fresh_host_is_a_fresh_install(tmp_path):
    assert "UPGRADE_MODE=false" in detect(tmp_path)


def test_an_env_left_by_an_unfinished_fresh_install_resumes_it(tmp_path):
    out = detect(tmp_path, env=True)
    assert "UPGRADE_MODE=false" in out
    assert "Unfinished fresh install found" in out


def test_a_completed_install_is_an_upgrade(tmp_path):
    assert "UPGRADE_MODE=true" in detect(tmp_path, identity=True, env=True)


def test_a_running_backend_is_an_upgrade(tmp_path):
    assert "UPGRADE_MODE=true" in detect(tmp_path, backend_active=True)


def test_an_install_from_before_the_identity_existed_is_still_an_upgrade(tmp_path):
    assert "UPGRADE_MODE=true" in detect(tmp_path, env=True, pg_data=True)


def pgdg(tmp: Path, *, lsb: str | None, os_release: str, served: bool):
    (tmp / "apt").mkdir()
    (tmp / "os-release").write_text(os_release)
    block = PGDG.replace("/etc/os-release", str(tmp / "os-release")).replace(
        "/etc/apt/sources.list.d", str(tmp / "apt"))
    lsb_fn = f"lsb_release() {{ echo {lsb}; }}" if lsb else "lsb_release() { return 127; }"
    script = f"""set -euo pipefail
cb_fail() {{ printf 'FAIL: %s\\n' "$1"; exit 7; }}
{lsb_fn}
curl() {{ printf '%s\\n' "${{@: -1}}" >> '{tmp}/curl-calls'; {'return 0' if served else 'return 22'}; }}
f() {{
{block}
}}
f
cat '{tmp}/apt/pgdg.list'
"""
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)


def test_pgdg_uses_os_release_when_lsb_release_is_missing(tmp_path):
    result = pgdg(tmp_path, lsb=None, os_release="VERSION_CODENAME=resolute\n", served=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "/apt resolute-pgdg main" in result.stdout
    assert (tmp_path / "curl-calls").read_text().strip() == \
        "http://apt.postgresql.org/pub/repos/apt/dists/resolute-pgdg/Release"


def test_pgdg_prefers_lsb_release(tmp_path):
    result = pgdg(tmp_path, lsb="noble", os_release="VERSION_CODENAME=other\n", served=True)
    assert "/apt noble-pgdg main" in result.stdout


def test_a_release_pgdg_does_not_serve_fails_before_writing_the_repository(tmp_path):
    result = pgdg(tmp_path, lsb="futurecodename", os_release="", served=False)
    assert result.returncode == 7
    assert "has no packages for 'futurecodename' yet" in result.stdout
    assert not (tmp_path / "apt/pgdg.list").exists()


def test_no_codename_at_all_fails_clearly(tmp_path):
    result = pgdg(tmp_path, lsb=None, os_release="NAME=Something\n", served=True)
    assert result.returncode == 7
    assert "no VERSION_CODENAME" in result.stdout
