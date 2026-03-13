#!/usr/bin/env python3
"""Build and package native Circuit Breaker release artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
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

    hidden_imports = [
        "aiosqlite",  # SQLAlchemy async SQLite driver (lazy-loaded)
        "greenlet",   # Used by aiosqlite
    ]
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
            *[f"--hidden-import={m}" for m in hidden_imports],
            str(BACKEND_ENTRYPOINT),
        ]
    )
    binary_path = dist_dir / binary_name(target_os)
    if not binary_path.exists():
        raise SystemExit(f"Expected PyInstaller output missing: {binary_path}")
    return binary_path


def _write_env_example(bundle_dir: Path) -> None:
    """Generate a .env.example tailored to native (non-Docker) deployments."""
    text = """\
# Circuit Breaker — environment variables for native binary deployments.
# Copy this file to .env (next to the binary) and fill in the values.
# The binary reads .env automatically on startup; explicit exports also work.

# ── Required ─────────────────────────────────────────────────────────────────
# Fernet encryption key for the credential vault.
# Generate: openssl rand -base64 32
CB_VAULT_KEY=

# PostgreSQL connection string (database must already exist).
CB_DB_URL=postgresql://circuitbreaker:changeme@127.0.0.1:5432/circuitbreaker

# ── Optional ─────────────────────────────────────────────────────────────────
# Host and port the web server listens on.
# CB_HOST=0.0.0.0
# CB_PORT=8080

# Redis URL for telemetry cache and pub/sub (omit to disable).
# CB_REDIS_URL=redis://127.0.0.1:6379/0

# Connection pool tuning (defaults: 10 / 10).
# DB_POOL_SIZE=10
# DB_MAX_OVERFLOW=10

# Data and log directories.
# CB_DATA_DIR=/var/lib/circuit-breaker
# CB_LOG_DIR=/var/log/circuit-breaker

# Path to the bundled frontend assets (auto-detected from share/frontend).
# STATIC_DIR=./share/frontend

# Path to alembic.ini for database migrations (auto-detected from share/).
# CB_ALEMBIC_INI=./share/backend/alembic.ini
"""
    (bundle_dir / ".env.example").write_text(text, encoding="utf-8")


def _write_readme(bundle_dir: Path, version: str, target_os: str, binary: str) -> None:
    """Generate a quick-start README.txt placed at the archive root."""
    run_prefix = "./" if target_os != "windows" else ""
    text = f"""\
Circuit Breaker {version} — Quick Start
{'=' * 42}

Prerequisites
-------------
- PostgreSQL 14+ (running and accessible)
- openssl  (for generating secrets)

1. Generate a vault encryption key
-----------------------------------
  openssl rand -base64 32

  Copy the output — you will use it as CB_VAULT_KEY below.

2. Configure environment
-------------------------
  Copy the included .env.example to .env and fill in values:

    cp .env.example .env

  At minimum, set CB_VAULT_KEY (from step 1) and CB_DB_URL.

3. Run Circuit Breaker
-----------------------
  {run_prefix}{binary}

  The binary reads .env automatically. You can also export vars directly:

  CB_VAULT_KEY="<key>" CB_DB_URL="postgresql://..." {run_prefix}{binary}

  The web UI will be available at http://localhost:8080 by default.

4. Configuration (optional)
----------------------------
  A sample config file is included at:

    share/config.toml.default

  Copy it to /etc/circuit-breaker/config.toml (Linux) or pass
  --config <path> to the binary. Environment variables always
  take precedence over config file values.

Archive contents
-----------------
  {binary}                  — Application binary
  README.txt                — This file
  .env.example              — Environment variable template
  manifest.json             — Build metadata (version, arch, checksums)
  share/VERSION             — Version string
  share/frontend/           — Pre-built web UI assets
  share/backend/alembic.ini — Database migration config
  share/backend/migrations/ — Database migration scripts
  share/config.toml.default — Sample configuration file

Full documentation
-------------------
  https://github.com/BlkLeg/circuitbreaker
"""
    (bundle_dir / "README.txt").write_text(text, encoding="utf-8")


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

    # Bundle config.toml template if present
    config_default = REPO_ROOT / "packaging" / "config.toml.default"
    if config_default.exists():
        shutil.copy2(config_default, share_dir / "config.toml.default")

    # Bundle launchd plist template if present
    plist_template = REPO_ROOT / "packaging" / "com.blkleg.circuitbreaker.plist"
    if plist_template.exists():
        shutil.copy2(plist_template, share_dir / "com.blkleg.circuitbreaker.plist")

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

    _write_readme(bundle_dir, version, target_os, binary_path.name)
    _write_env_example(bundle_dir)

    return bundle_dir, manifest


def create_archive(bundle_dir: Path, version: str, target_os: str, target_arch: str, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    if not os.access(output_dir, os.W_OK):
        raise SystemExit(
            f"Output directory is not writable: {output_dir}\n"
            "  (possibly left behind by a root-owned build). Fix ownership, for example:\n"
            f"  sudo chown -R \"$USER\":\"$USER\" {output_dir}"
        )
    archive_path = output_dir / archive_name(version, target_os, target_arch)
    if archive_path.exists():
        try:
            archive_path.unlink()
        except PermissionError as e:
            raise SystemExit(
                f"Archive exists and cannot be removed: {archive_path}\n"
                f"  (possibly created by root). Remove it manually:\n"
                f"  sudo rm {archive_path}"
            ) from e

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


def create_linux_packages(
    bundle_dir: Path, version: str, target_arch: str, output_dir: Path
) -> list[Path]:
    """Generate .deb and .rpm packages using nfpm."""
    nfpm = shutil.which("nfpm")
    if not nfpm:
        print("nfpm not found — skipping deb/rpm generation. Install: https://nfpm.goreleaser.com/install/")
        return []

    nfpm_config = REPO_ROOT / "nfpm.yaml"
    if not nfpm_config.exists():
        print("nfpm.yaml not found — skipping deb/rpm generation.")
        return []

    # nfpm uses GOARCH naming
    arch_map = {"amd64": "amd64", "arm64": "arm64"}
    goarch = arch_map.get(target_arch, target_arch)

    # Symlink bundle contents to where nfpm.yaml expects them
    dist_bundle = REPO_ROOT / "dist" / "native" / "bundle"
    if dist_bundle.exists():
        shutil.rmtree(dist_bundle)
    shutil.copytree(bundle_dir, dist_bundle)

    env = {
        **os.environ,
        "VERSION": version,
        "GOARCH": goarch,
    }

    packages: list[Path] = []
    for fmt in ("deb", "rpm"):
        pkg_path = output_dir / f"circuit-breaker_{version}_{goarch}.{fmt}"
        result = subprocess.run(
            [nfpm, "package", "--config", str(nfpm_config), "--packager", fmt,
             "--target", str(pkg_path)],
            env=env, cwd=str(REPO_ROOT), capture_output=True, text=True,
        )
        if result.returncode == 0:
            print(f"  Created: {pkg_path.name}")
            packages.append(pkg_path)
        else:
            print(f"  WARNING: {fmt} packaging failed: {result.stderr.strip()}")

    return packages


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

    # Generate deb/rpm if on Linux
    if target_os == "linux":
        create_linux_packages(bundle_dir, version, target_arch, output_dir)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
