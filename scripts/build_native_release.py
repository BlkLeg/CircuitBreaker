#!/usr/bin/env python3
"""Build and package native Circuit Breaker release artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_ENTRYPOINT = REPO_ROOT / "apps" / "backend" / "src" / "app" / "start.py"
FRONTEND_DIST = REPO_ROOT / "apps" / "frontend" / "dist"
BACKEND_ROOT = REPO_ROOT / "apps" / "backend"
VERSION_FILE = REPO_ROOT / "VERSION"
DOCS_SEED_FILE = REPO_ROOT / "DocsPage.md"


def detect_target() -> tuple[str, str]:
    system = platform.system().lower()
    machine = platform.machine().lower()

    os_map = {
        "linux": "linux",
        "darwin": "macos",
        "windows": "windows",
    }
    arch_map = {
        "x86_64": "amd64",
        "amd64": "amd64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }

    target_os = os_map.get(system)
    target_arch = arch_map.get(machine)
    if not target_os or not target_arch:
        raise SystemExit(f"Unsupported native packaging target: {system}/{machine}")
    return target_os, target_arch


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build native Circuit Breaker release artifacts.")
    parser.add_argument(
        "--version",
        default=VERSION_FILE.read_text(encoding="utf-8").strip(),
        help="Version string used in the output asset names.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete the work directory before building.",
    )
    return parser.parse_args()


def sanitize_version(version: str) -> str:
    value = version.strip()
    if not value or not re.fullmatch(r"[A-Za-z0-9._-]+", value):
        raise SystemExit(f"Unsupported version string for archive naming: {version!r}")
    return value


def run(cmd: list[str], *, cwd: Path | None = None) -> None:
    subprocess.run(cmd, cwd=cwd or REPO_ROOT, check=True)


def sha256sum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def archive_name(version: str, target_os: str, target_arch: str) -> str:
    suffix = "zip" if target_os == "windows" else "tar.gz"
    return f"circuit-breaker_{version}_{target_os}_{target_arch}.{suffix}"


def binary_name(target_os: str) -> str:
    return "circuit-breaker.exe" if target_os == "windows" else "circuit-breaker"


def ensure_frontend_dist(frontend_dir: Path) -> None:
    if not frontend_dir.exists():
        raise SystemExit(
            f"Frontend dist directory not found at {frontend_dir}. Run the frontend build first."
        )


def build_binary(target_os: str, work_dir: Path) -> Path:
    dist_dir = work_dir / "pyinstaller-dist"
    build_dir = work_dir / "pyinstaller-build"
    spec_dir = work_dir / "pyinstaller-spec"
    dist_dir.mkdir(parents=True, exist_ok=True)
    build_dir.mkdir(parents=True, exist_ok=True)
    spec_dir.mkdir(parents=True, exist_ok=True)

    run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--onefile",
            "--clean",
            "--distpath",
            str(dist_dir),
            "--workpath",
            str(build_dir),
            "--specpath",
            str(spec_dir),
            "--name",
            binary_name(target_os),
            str(BACKEND_ENTRYPOINT),
        ]
    )
    binary_path = dist_dir / binary_name(target_os)
    if not binary_path.exists():
        raise SystemExit(f"Expected PyInstaller output missing: {binary_path}")
    return binary_path


def stage_bundle(
    binary_path: Path,
    version: str,
    target_os: str,
    target_arch: str,
    frontend_dir: Path,
    work_dir: Path,
) -> tuple[Path, dict[str, object]]:
    bundle_dir = work_dir / f"bundle-{target_os}-{target_arch}"
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    share_dir = bundle_dir / "share"
    backend_share = share_dir / "backend"
    frontend_share = share_dir / "frontend"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    backend_share.mkdir(parents=True, exist_ok=True)

    shutil.copy2(binary_path, bundle_dir / binary_path.name)
    shutil.copy2(VERSION_FILE, share_dir / "VERSION")
    shutil.copy2(DOCS_SEED_FILE, share_dir / "DocsPage.md")
    shutil.copy2(BACKEND_ROOT / "alembic.ini", backend_share / "alembic.ini")
    shutil.copytree(BACKEND_ROOT / "migrations", backend_share / "migrations", dirs_exist_ok=True)
    shutil.copytree(frontend_dir, frontend_share, dirs_exist_ok=True)

    manifest = {
        "app": "Circuit Breaker",
        "version": version,
        "os": target_os,
        "arch": target_arch,
        "archive": archive_name(version, target_os, target_arch),
        "binary": binary_path.name,
        "share_dir": "share",
        "resources": {
            "version": "share/VERSION",
            "docs_seed": "share/DocsPage.md",
            "frontend": "share/frontend",
            "alembic_ini": "share/backend/alembic.ini",
            "migrations": "share/backend/migrations",
        },
    }
    (bundle_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return bundle_dir, manifest


def create_archive(bundle_dir: Path, version: str, target_os: str, target_arch: str, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / archive_name(version, target_os, target_arch)
    if archive_path.exists():
        archive_path.unlink()

    if target_os == "windows":
        with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
            for file_path in sorted(bundle_dir.rglob("*")):
                if file_path.is_file():
                    archive.write(file_path, file_path.relative_to(bundle_dir))
    else:
        with tarfile.open(archive_path, "w:gz") as archive:
            for file_path in sorted(bundle_dir.rglob("*")):
                archive.add(file_path, arcname=file_path.relative_to(bundle_dir))
    return archive_path


def write_metadata(output_dir: Path, manifest: dict[str, object], archive_path: Path) -> None:
    digest = sha256sum(archive_path)
    checksum_path = archive_path.with_suffix(archive_path.suffix + ".sha256")
    checksum_path.write_text(f"{digest}  {archive_path.name}\n", encoding="utf-8")

    manifest_with_checksum = {**manifest, "sha256": digest}
    if archive_path.name.endswith(".tar.gz"):
        manifest_name = archive_path.name[: -len(".tar.gz")] + ".json"
    else:
        manifest_name = archive_path.stem + ".json"
    (output_dir / manifest_name).write_text(
        json.dumps(manifest_with_checksum, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    target_os, target_arch = detect_target()
    version = sanitize_version(args.version)
    output_dir = REPO_ROOT / "dist" / "native"
    work_dir = REPO_ROOT / "build" / "native-release" / f"{target_os}-{target_arch}"
    frontend_dir = FRONTEND_DIST

    ensure_frontend_dist(frontend_dir)
    if args.clean and work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    binary_path = build_binary(target_os, work_dir)
    bundle_dir, manifest = stage_bundle(
        binary_path=binary_path,
        version=version,
        target_os=target_os,
        target_arch=target_arch,
        frontend_dir=frontend_dir,
        work_dir=work_dir,
    )
    archive_path = create_archive(bundle_dir, version, target_os, target_arch, output_dir)
    write_metadata(output_dir, manifest, archive_path)
    print(archive_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
