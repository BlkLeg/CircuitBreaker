#!/usr/bin/env python3
"""Build and package native Circuit Breaker release artifacts."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
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


def ensure_pyinstaller_available() -> None:
    if importlib.util.find_spec("PyInstaller") is not None:
        return
    raise SystemExit(
        "PyInstaller is required for native packaging but is not installed in the active Python environment.\n"
        "Install backend dev dependencies first, for example:\n"
        "  .venv/bin/pip install -e \"apps/backend[dev]\"\n"
        "Or install PyInstaller directly:\n"
        "  .venv/bin/pip install pyinstaller"
    )


def build_binary(target_os: str, work_dir: Path) -> Path:
    dist_dir = work_dir / "pyinstaller-dist"
    build_dir = work_dir / "pyinstaller-build"
    spec_dir = work_dir / "pyinstaller-spec"
    dist_dir.mkdir(parents=True, exist_ok=True)
    build_dir.mkdir(parents=True, exist_ok=True)
    spec_dir.mkdir(parents=True, exist_ok=True)

    hidden_imports = [
        "greenlet",   # Required by SQLAlchemy async
        "app.workers",
        "app.workers.main",
        "app.workers.discovery",
        "app.workers.webhook_worker",
        "app.workers.notification_worker",
        "app.workers.telemetry_collector",
        "app.workers.status_worker",
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

    # Bundle installer infrastructure for curl-pipe / Proxmox installs
    deploy_src = REPO_ROOT / "deploy"
    deploy_dst = bundle_dir / "deploy"
    for subdir in ("config", "systemd", "nginx", "cli", "misc", "scripts"):
        src = deploy_src / subdir
        if src.exists():
            shutil.copytree(src, deploy_dst / subdir, dirs_exist_ok=True)
    shutil.copy2(deploy_src / "setup.sh", deploy_dst / "setup.sh")
    installer_src = REPO_ROOT / "install.sh"
    if installer_src.exists():
        shutil.copy2(installer_src, bundle_dir / "install.sh")

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
            "deploy": "deploy",
            "installer": "install.sh",
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
    for fmt in ("deb", "rpm", "apk"):
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


def create_appimage(
    bundle_dir: Path, version: str, target_arch: str, output_dir: Path
) -> Path | None:
    """Generate .AppImage for amd64 only."""
    if target_arch != "amd64":
        print("  AppImage: skipping (amd64 only)")
        return None

    appimagetool = shutil.which("appimagetool")
    if not appimagetool:
        print("appimagetool not found — skipping AppImage. Install: https://appimage.github.io/appimagetool/")
        return None

    appdir = output_dir / "CircuitBreaker.AppDir"
    if appdir.exists():
        shutil.rmtree(appdir)

    bin_dir = appdir / "usr" / "bin"
    share_dir = appdir / "usr" / "share" / "circuit-breaker"
    bin_dir.mkdir(parents=True)
    share_dir.mkdir(parents=True)

    shutil.copy2(bundle_dir / "circuit-breaker", bin_dir / "circuit-breaker")
    (bin_dir / "circuit-breaker").chmod(0o755)

    src_share = bundle_dir / "share"
    if src_share.exists():
        shutil.copytree(src_share, share_dir, dirs_exist_ok=True)

    apprun = appdir / "AppRun"
    apprun.write_text(
        '#!/bin/sh\nexec "$(dirname "$(readlink -f "$0")")/usr/bin/circuit-breaker" "$@"\n'
    )
    apprun.chmod(0o755)

    (appdir / "circuit-breaker.desktop").write_text(
        "[Desktop Entry]\n"
        "Version=1.0\n"
        "Type=Application\n"
        "Name=Circuit Breaker\n"
        "Comment=Homelab topology, documented.\n"
        "Exec=circuit-breaker\n"
        "Icon=circuit-breaker\n"
        "Categories=Network;System;\n"
        "Terminal=false\n"
    )

    icon_src = bundle_dir / "circuit-breaker.png"
    icon_dst = appdir / "circuit-breaker.png"
    if icon_src.exists():
        shutil.copy2(icon_src, icon_dst)
    else:
        import base64
        _TRANSPARENT_PNG = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        )
        icon_dst.write_bytes(_TRANSPARENT_PNG)

    appimage_path = output_dir / f"circuit-breaker-{version}-x86_64.AppImage"
    try:
        result = subprocess.run(
            [appimagetool, str(appdir), str(appimage_path)],
            capture_output=True,
            text=True,
            env={**os.environ, "ARCH": "x86_64"},
        )
    finally:
        if appdir.exists():
            shutil.rmtree(appdir)

    if result.returncode == 0:
        print(f"  Created: {appimage_path.name}")
        return appimage_path
    else:
        print(f"  WARNING: AppImage creation failed: {result.stderr.strip()}")
        return None


def create_arch_package(
    bundle_dir: Path, version: str, target_arch: str, output_dir: Path, tarball_path: Path
) -> Path | None:
    """Generate .pkg.tar.zst using makepkg with a local-source patched PKGBUILD."""
    makepkg = shutil.which("makepkg")
    if not makepkg:
        print("makepkg not found — skipping Arch package generation.")
        return None

    pkgbuild = REPO_ROOT / "PKGBUILD"
    if not pkgbuild.exists():
        print("PKGBUILD not found — skipping Arch package generation.")
        return None

    arch_map = {"amd64": "x86_64", "arm64": "aarch64"}
    pkg_arch = arch_map.get(target_arch, target_arch)

    work_dir = output_dir / "arch-pkg-build"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)

    # Copy tarball into work_dir so makepkg can find it as a local source
    local_tarball = work_dir / tarball_path.name
    shutil.copy2(tarball_path, local_tarball)

    # Patch PKGBUILD: swap remote source URL → local filename, pin version
    pkgbuild_text = pkgbuild.read_text()
    patched = re.sub(
        r'(source_(?:x86_64|aarch64)=\().*?(\))',
        f'source_{pkg_arch}=("{tarball_path.name}")',
        pkgbuild_text,
    )
    patched = re.sub(r"sha256sums_(?:x86_64|aarch64)=\('[^']*'\)", f"sha256sums_{pkg_arch}=('SKIP')", patched)
    patched = re.sub(r'^pkgver=.*', f'pkgver={version}', patched, flags=re.MULTILINE)
    (work_dir / "PKGBUILD").write_text(patched)

    env = {**os.environ, "PKGDEST": str(output_dir), "SRCDEST": str(work_dir)}
    try:
        result = subprocess.run(
            [makepkg, "--nodeps", "--nocheck", "--noconfirm", "-f"],
            env=env,
            cwd=str(work_dir),
            capture_output=True,
            text=True,
        )
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    if result.returncode != 0:
        print(f"  WARNING: Arch package creation failed:\n{result.stderr.strip()}")
        return None

    pkgs = sorted(output_dir.glob("*.pkg.tar.zst"))
    if pkgs:
        print(f"  Created: {pkgs[-1].name}")
        return pkgs[-1]

    print("  WARNING: makepkg succeeded but no .pkg.tar.zst found in output dir")
    return None


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

    ensure_pyinstaller_available()
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

    # Generate Linux packages
    if target_os == "linux":
        create_linux_packages(bundle_dir, version, target_arch, output_dir)
        create_appimage(bundle_dir, version, target_arch, output_dir)
        create_arch_package(bundle_dir, version, target_arch, output_dir, archive_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
