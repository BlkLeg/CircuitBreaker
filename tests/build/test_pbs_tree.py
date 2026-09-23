"""scripts/pbs_tree.py assembles the hermetic runtime tree.

Everything here runs without network and without a real interpreter download:
the pieces that need one (pip, compileall, --selftest) are monkeypatched, and
the one test that builds a real tree runs only when a build has produced one.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tarfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import pbs_tree  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
PIN = REPO_ROOT / "packaging" / "python-build-standalone.pin"
REAL_TREE = REPO_ROOT / "dist" / "native" / "bundle"


def _fake_pbs_archive(path: Path) -> Path:
    """A tarball shaped like an install_only PBS release: one python/ root."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data, mode in (
            ("python/bin/python3.12", b"\x7fELF-fake\x00GLIBC_2.17\x00GLIBC_2.28\x00", 0o755),
            ("python/lib/python3.12/site-packages/README.txt", b"site\n", 0o644),
            ("python/lib/libpython3.12.so.1.0", b"\x7fELF-fake\x00GLIBC_2.34\x00", 0o755),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = mode
            tar.addfile(info, io.BytesIO(data))
        link = tarfile.TarInfo("python/bin/python3")
        link.type = tarfile.SYMTYPE
        link.linkname = "python3.12"
        tar.addfile(link)
    path.write_bytes(buf.getvalue())
    return path


def test_pin_file_names_every_field_the_build_reads():
    pin = pbs_tree.read_pin(PIN)
    assert pin.release and pin.python.startswith("3.12.")
    assert set(pin.sha256) == {"amd64", "arm64"}
    for digest in pin.sha256.values():
        assert len(digest) == 64 and int(digest, 16) >= 0


def test_asset_name_and_url_follow_the_distributor_layout():
    pin = pbs_tree.PbsPin(release="20260101", python="3.12.9", sha256={"amd64": "0" * 64, "arm64": "1" * 64})
    assert pbs_tree.asset_name(pin, "amd64") == (
        "cpython-3.12.9+20260101-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz"
    )
    assert pbs_tree.asset_url(pin, "arm64").endswith(
        "/releases/download/20260101/cpython-3.12.9+20260101-aarch64-unknown-linux-gnu-install_only_stripped.tar.gz"
    )


def test_fetch_refuses_a_digest_mismatch(tmp_path, monkeypatch):
    archive = _fake_pbs_archive(tmp_path / "pbs.tar.gz")
    pin = pbs_tree.PbsPin(release="r", python="3.12.9", sha256={"amd64": "0" * 64, "arm64": "1" * 64})
    monkeypatch.setattr(
        pbs_tree.urllib.request, "urlretrieve",
        lambda url, dest: Path(dest).write_bytes(archive.read_bytes()),
    )
    with pytest.raises(SystemExit, match="digest"):
        pbs_tree.fetch_interpreter(pin, "amd64", tmp_path / "cache")
    assert not list((tmp_path / "cache").glob("*.tar.gz")), "a mismatched download must not be cached"


def test_unpack_rejects_an_archive_without_a_single_python_root(tmp_path):
    bad = tmp_path / "bad.tar.gz"
    with tarfile.open(bad, "w:gz") as tar:
        info = tarfile.TarInfo("bin/python3")
        info.size = 0
        tar.addfile(info, io.BytesIO(b""))
    with pytest.raises(SystemExit, match="python/"):
        pbs_tree.unpack_interpreter(bad, tmp_path / "tree")


def test_glibc_floor_is_the_highest_symbol_version_in_any_elf(tmp_path):
    tree = tmp_path / "tree"
    pbs_tree.unpack_interpreter(_fake_pbs_archive(tmp_path / "pbs.tar.gz"), tree)
    assert pbs_tree.glibc_floor(tree) == "2.34"


def test_launchers_are_isolated_and_export_the_share_dir(tmp_path):
    tree = tmp_path / "tree"
    (tree / "python" / "bin").mkdir(parents=True)
    pbs_tree.write_launchers(tree)
    launcher = (tree / "bin" / "circuit-breaker").read_text()
    wrapper = (tree / "bin" / "cb-python").read_text()
    assert launcher.startswith("#!/bin/sh\n")
    assert 'exec "$root/python/bin/python3" -I -B -X utf8 -m app.start "$@"' in launcher
    assert 'exec "$root/python/bin/python3" -I -B -X utf8 "$@"' in wrapper
    for text in (launcher, wrapper):
        assert 'readlink -f "$0"' in text, "a symlink in /usr/local/bin must resolve to the tree"
        assert ': "${CB_SHARE_DIR:=$root/share}"' in text
    assert os.access(tree / "bin" / "circuit-breaker", os.X_OK)


def test_runtime_digest_ignores_mtime_and_changes_with_content(tmp_path):
    tree = tmp_path / "tree"
    for rel in ("python/bin/python3.12", "bin/circuit-breaker", "share/backend/alembic.ini"):
        path = tree / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rel)
    first = pbs_tree.runtime_digest(tree)
    os.utime(tree / "bin" / "circuit-breaker", (0, 0))
    assert pbs_tree.runtime_digest(tree) == first
    (tree / "share" / "frontend").mkdir(parents=True)
    (tree / "share" / "frontend" / "index.html").write_text("<html/>")
    assert pbs_tree.runtime_digest(tree) == first, "share/frontend is not part of the runtime digest"
    (tree / "share" / "backend" / "alembic.ini").write_text("changed")
    assert pbs_tree.runtime_digest(tree) != first


def test_build_tree_lays_out_the_runtime_and_records_provenance(tmp_path, monkeypatch):
    archive = _fake_pbs_archive(tmp_path / "pbs.tar.gz")
    pin = pbs_tree.PbsPin(release="r1", python="3.12.9", sha256={"amd64": pbs_tree.sha256_file(archive), "arm64": "1" * 64})
    monkeypatch.setattr(pbs_tree, "read_pin", lambda path=None: pin)
    monkeypatch.setattr(pbs_tree, "fetch_interpreter", lambda pin, arch, cache: archive)

    def fake_install(tree: Path, requirement_files: tuple[Path, ...]) -> None:
        site = pbs_tree.site_packages(tree)
        (site / "app").mkdir()
        (site / "app" / "__init__.py").write_text("")
        (site / "app" / "direct_url.json").write_text("{}")
        (site / "pip").mkdir()
        (site / "pip-25.0.dist-info").mkdir()

    monkeypatch.setattr(pbs_tree, "install_dependencies", fake_install)
    monkeypatch.setattr(pbs_tree, "compile_bytecode", lambda tree: None)
    monkeypatch.setattr(pbs_tree, "assert_tree_contains_application", lambda tree: None)
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<html/>")

    tree = pbs_tree.build_tree(
        arch="amd64", version="9.9.9", output=tmp_path / "out", cache_dir=tmp_path / "cache",
        frontend_dist=frontend, agent_dist=None,
    )

    assert (tree / "python" / "bin" / "python3").is_symlink()
    assert (tree / "bin" / "circuit-breaker").is_file()
    assert (tree / "share" / "VERSION").read_text().strip() == "9.9.9"
    assert (tree / "share" / "backend" / "alembic.ini").is_file()
    assert (tree / "share" / "backend" / "migrations" / "env.py").is_file()
    assert (tree / "share" / "frontend" / "index.html").is_file()
    site = pbs_tree.site_packages(tree)
    assert not (site / "pip").exists() and not list(site.glob("pip-*.dist-info"))
    assert not list(site.rglob("direct_url.json"))
    info = json.loads((tree / "share" / "build-info.json").read_text())
    assert info["runtime"] == "pbs"
    assert info["pbs_release"] == "r1" and info["python"] == "3.12.9"
    assert info["glibc"] == info["glibc_floor"] == "2.34"
    assert info["runtime_digest"] == pbs_tree.runtime_digest(tree)
    assert len(info["lock_sha256"]) == 64
    assert info["built_by"] in {"ci", "local"}


def test_build_tree_is_deterministic_across_two_runs(tmp_path, monkeypatch):
    archive = _fake_pbs_archive(tmp_path / "pbs.tar.gz")
    pin = pbs_tree.PbsPin(release="r1", python="3.12.9", sha256={"amd64": pbs_tree.sha256_file(archive), "arm64": "1" * 64})
    monkeypatch.setattr(pbs_tree, "read_pin", lambda path=None: pin)
    monkeypatch.setattr(pbs_tree, "fetch_interpreter", lambda pin, arch, cache: archive)
    monkeypatch.setattr(pbs_tree, "install_dependencies", lambda tree, files: None)
    monkeypatch.setattr(pbs_tree, "compile_bytecode", lambda tree: None)
    monkeypatch.setattr(pbs_tree, "assert_tree_contains_application", lambda tree: None)
    digests = set()
    for run in ("a", "b"):
        tree = pbs_tree.build_tree(arch="amd64", version="9.9.9", output=tmp_path / run, cache_dir=tmp_path / "cache",
                                   frontend_dist=None, agent_dist=None)
        digests.add(json.loads((tree / "share" / "build-info.json").read_text())["runtime_digest"])
    assert len(digests) == 1


def test_the_real_tree_passes_its_own_contract():
    """Runs only after `scripts/build_native_release.py --packaging pbs` produced a tree."""
    if not (REAL_TREE / "python" / "bin" / "python3").exists():
        pytest.skip("no built PBS tree in dist/native/bundle — run `make build` first")
    info = json.loads((REAL_TREE / "share" / "build-info.json").read_text())
    assert info["runtime"] == "pbs"
    assert info["runtime_digest"] == pbs_tree.runtime_digest(REAL_TREE)
    assert not list(pbs_tree.site_packages(REAL_TREE).rglob("direct_url.json"))
    pbs_tree.assert_tree_contains_application(REAL_TREE)
