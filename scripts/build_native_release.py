#!/usr/bin/env python3
"""Build and package native Circuit Breaker release artifacts."""

from __future__ import annotations

import argparse
import ast
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
import tempfile
import urllib.request
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_ENTRYPOINT = REPO_ROOT / "apps" / "backend" / "src" / "app" / "start.py"
FRONTEND_DIST = REPO_ROOT / "apps" / "frontend" / "dist"
BACKEND_ROOT = REPO_ROOT / "apps" / "backend"
VERSION_FILE = REPO_ROOT / "VERSION"
DOCS_SEED_FILE = REPO_ROOT / "DocsPage.md"
AGENT_ROOT = REPO_ROOT / "apps" / "agent"

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pbs_tree  # noqa: E402  — sibling module; stdlib-only so the Docker stage can run it alone


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
    parser.add_argument(
        "--packaging",
        choices=["onefile", "onedir", "pbs"],
        default="pbs",
        help=(
            "'pbs' builds the hermetic python-build-standalone tree that every "
            "wrapper (tarball, deb/rpm/apk/Arch, AppImage, the mono image) ships. "
            "'onefile' is the retired PyInstaller path, kept for one release cycle "
            "as an emergency rollback; 'onedir' is PyInstaller's directory mode."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "dist" / "native",
        help=(
            "Directory to write the archive, checksums, manifest, and any "
            "Linux packages into. Defaults to dist/native, the existing "
            "location, so callers that do not pass this flag are unaffected."
        ),
    )
    return parser.parse_args()


def sanitize_version(version: str) -> str:
    """The version used for artifact names, checked against the one shipped.

    `--version` names the archive, the .deb, the .rpm and the manifest.
    ``share/VERSION`` is a straight copy of the repo's VERSION file, and the
    binary answers ``--version`` from that same file embedded at build time.
    Nothing reconciles the two, so a caller passing a different string produces
    a package whose *name* claims one version and whose *contents* report
    another.

    That is not hypothetical: dev-ci.yml built ``--version dev-<sha>`` while the
    bundle shipped ``0.4.3``, which is why the artifact-smoke contract could not
    run against a dev candidate — its version-parity assertions compare exactly
    these two values. Refusing here is what lets one gate definition serve the
    integration branch and the release tag.

    A build that wants a different version string changes VERSION; there is no
    override, because every consumer of an override would be a package that
    lies about itself.
    """
    value = version.strip()
    if not value or not re.fullmatch(r"[A-Za-z0-9._-]+", value):
        raise SystemExit(f"Unsupported version string for archive naming: {version!r}")

    shipped = VERSION_FILE.read_text(encoding="utf-8").strip()
    if value != shipped:
        raise SystemExit(
            f"--version {value!r} disagrees with {VERSION_FILE} ({shipped!r}).\n"
            "The bundle copies VERSION verbatim into share/VERSION and the binary\n"
            "reports it, so this build would produce artifacts named for a version\n"
            "they do not contain. Update VERSION, or drop --version to use it."
        )
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


def ensure_go_available() -> None:
    missing = [tool for tool in ("go", "make") if shutil.which(tool) is None]
    if not missing:
        return
    raise SystemExit(
        f"{' and '.join(missing)} required to cross-compile cb-agent binaries but not found on PATH.\n"
        "Install them first, for example:\n"
        "  bash scripts/install-build-deps.sh\n"
        "Or install Go (>=1.22) and make directly via your distro's package manager."
    )


def build_agent_binaries(version: str, work_dir: Path) -> Path:
    """Cross-compile cb-agent (linux/amd64 + linux/arm64) and write its
    manifest.json, isolated under work_dir so this can never read or write
    a developer's own local apps/agent/dist/ build artifacts."""
    agent_dist = work_dir / "agent-dist"
    subprocess.run(
        ["make", "manifest"],
        cwd=AGENT_ROOT,
        # PYTHON: gen_manifest.py's signing step imports `cryptography`,
        # which lives in this interpreter's environment and not necessarily
        # in whatever bare `python3` the agent Makefile would otherwise
        # resolve to.
        env={
            **os.environ,
            "VERSION": version,
            "DIST": str(agent_dist / version),
            "PYTHON": sys.executable,
            # The ldflag that embeds the verifying key in the
            # built binaries. os.environ already carries it, but naming it
            # here keeps the two halves of the signing contract — the private
            # key gen_manifest.py reads and the public key build-all embeds —
            # visible in one place.
            "SIGNING_PUBKEY": os.environ.get("SIGNING_PUBKEY", ""),
        },
        check=True,
    )
    return agent_dist


def _collect_migration_hidden_imports() -> list[str]:
    """Alembic loads migrations/versions/*.py dynamically at runtime — they
    are never reached by PyInstaller's static import-graph analysis from
    start.py. Any `app.*` module a migration imports (e.g. a one-off
    backfill helper used by exactly one migration and nowhere else in the
    live app) is silently left out of the frozen binary unless declared as
    a hidden import. Scan every migration file for `app.*` imports instead
    of hand-maintaining that list, so this can't quietly regress again as
    new migrations are added.
    """
    versions_dir = BACKEND_ROOT / "migrations" / "versions"
    found: set[str] = set()
    for path in sorted(versions_dir.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "app" or alias.name.startswith("app."):
                        found.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module and (node.module == "app" or node.module.startswith("app.")):
                    found.add(node.module)
    return sorted(found)


def _collect_asgi_target_hidden_imports() -> list[str]:
    """The API server is named in a string, so nothing imports it.

    `start.py` ends in `uvicorn.run("app.main:app", ...)`. uvicorn resolves that
    with `importlib.import_module`, which PyInstaller's static graph cannot see,
    so `app.main` — the entire application — only ever entered the frozen binary
    because a line above it happened to read `from app.main import
    run_alembic_upgrade`. Splitting that helper out into `app.startup.schema`
    removed the last static reference and 0.4.2 shipped a binary with no
    application in it: migrations ran, then every native install died on

        ERROR: Error loading ASGI app. Could not import module "app.main".

    Reading the name back out of the call keeps the hidden import tied to what
    the entrypoint actually serves, so a future rename of `main.py` moves it
    instead of silently emptying the binary again.
    """
    tree = ast.parse(
        BACKEND_ENTRYPOINT.read_text(encoding="utf-8"), filename=str(BACKEND_ENTRYPOINT)
    )
    found: set[str] = set()
    launches = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        if not (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "uvicorn"
            and func.attr in {"run", "Config"}
        ):
            continue
        launches += 1
        target = node.args[0]
        if not (isinstance(target, ast.Constant) and isinstance(target.value, str)):
            # An application object rather than an import string: whatever
            # defines it is reached by the static graph already.
            continue
        module_str, separator, _ = target.value.partition(":")
        if not separator or not module_str:
            raise SystemExit(
                f"{BACKEND_ENTRYPOINT.name} passes uvicorn the ASGI target "
                f"{target.value!r}, which is not in uvicorn's required "
                '"<module>:<attribute>" form. The binary would fail to boot.'
            )
        found.add(module_str)
    if not launches:
        raise SystemExit(
            f"Found no uvicorn launch in {BACKEND_ENTRYPOINT.name}, so the ASGI "
            "application it serves cannot be declared as a hidden import. "
            "PyInstaller drops modules named only in strings; a binary that boots "
            "straight into ImportFromStringError is worse than no binary."
        )
    return sorted(found)


# Third-party packages that reach part of themselves through a runtime string
# rather than an `import` statement. PyInstaller builds its bundle from a static
# import graph, so anything named only by a string is invisible to it and gets
# dropped -- the frozen binary then raises ModuleNotFoundError on the first call
# that needs it, with nothing at build time to warn you. Same class of problem
# `_collect_migration_hidden_imports()` above solves for Alembic's migrations.
#
#   proxmoxer  -- ProxmoxAPI.__init__ selects its auth backend with
#                 `importlib.import_module(f".backends.{backend}", "proxmoxer")`,
#                 so proxmoxer/backends/*.py never entered the bundle and every
#                 Proxmox VE integration on a native install died on connect.
#                 (gh#104)
#   apscheduler -- resolves triggers, executors and jobstores through
#                 `importlib.metadata.entry_points()`. We only ever pass trigger
#                 *objects* (`CronTrigger(...)`, never the "cron" alias) and
#                 never name a jobstore or executor, so this is pre-emptive: it
#                 covers a future caller who does. Note that entry-point lookup
#                 also needs the dist-info metadata, which submodules alone do
#                 not provide -- a caller who starts using string aliases needs
#                 `copy_metadata("APScheduler")` here as well.
#
# collect_submodules walks the installed package on disk instead of the import
# graph, so new backends are picked up without editing this list.
_DYNAMIC_IMPORT_PACKAGES = ("proxmoxer", "apscheduler")


def _collect_dynamic_import_hidden_imports() -> list[str]:
    """Enumerate submodules of packages that import parts of themselves by name.

    Imported inside the function because `ensure_pyinstaller_available()` only
    guarantees PyInstaller is importable by the time the build runs, not at
    module import time.

    Fails the build rather than warning: a package listed here is a declared
    runtime dependency, and silently shipping without it is exactly the failure
    this function exists to prevent.
    """
    from PyInstaller.utils.hooks import collect_submodules

    found: list[str] = []
    for package in _DYNAMIC_IMPORT_PACKAGES:
        try:
            submodules = collect_submodules(package)
        except Exception as exc:
            raise SystemExit(
                f"Could not enumerate submodules of {package!r}, which loads part of "
                f"itself dynamically and must be declared as a hidden import: {exc}\n"
                "Install the backend runtime dependencies into the active environment first."
            ) from exc
        if not submodules:
            raise SystemExit(
                f"{package!r} resolved to no submodules -- it is almost certainly not "
                "installed in the active environment. Refusing to build a binary that "
                "would fail at runtime instead."
            )
        found.extend(submodules)
    return sorted(set(found))


def assert_binary_contains_application(binary_path: Path) -> None:
    """Refuse to stage a binary that cannot import the application it serves.

    PyInstaller builds from a static import graph, so a module reached only
    through a runtime string is dropped silently. The three collectors above
    exist to re-declare the ones we know about; this asserts the outcome rather
    than trusting the inputs, which is the difference between a mitigation and
    a gate.

    v0.4.2 is what its absence costs: a binary with no `app.main` inside it was
    signed, attested, SBOM'd, version-parity-checked and published, and died on
    every native install. `--version` — the only thing any gate executed —
    resolves from an embedded VERSION file and returns before the application is
    imported, so it cannot observe the defect by construction.

    Runs in seconds, needs no services, and gates every package format at once:
    the tarball, deb, rpm, apk, AppImage and pkg.tar.zst all wrap this binary.

    Raises:
        SystemExit: if the binary reports a self-test failure or cannot be run.
    """
    print(f"Verifying {binary_path.name} contains its application...")
    completed = subprocess.run(
        [str(binary_path), "--selftest"],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
        env={**os.environ, "CB_DB_URL": "postgresql://fake:fake@localhost/fake"},
    )
    output = (completed.stdout + completed.stderr).strip()
    if completed.returncode != 0:
        raise SystemExit(
            f"{binary_path.name} failed its self-test (exit {completed.returncode}).\n"
            f"{output}\n\n"
            "The frozen binary cannot import something it needs at runtime — "
            "almost always a module named only by a string, which PyInstaller's "
            "static import graph cannot see. Add it to hidden_imports in "
            "build_binary(), or to the collector that should have found it.\n"
            "Refusing to stage a bundle that would fail on every install."
        )
    print(f"  {output}")

def build_binary(target_os: str, work_dir: Path, packaging_mode: str = "onefile") -> Path:
    if packaging_mode == "pbs":
        raise SystemExit("build_binary is the PyInstaller path; --packaging pbs is assembled by pbs_tree.build_tree")

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
        "app.workers.notification_worker",
        "app.workers.telemetry_collector",
        "app.workers.monitor_scheduler",
        "app.workers.monitor_poll_worker",
        *_collect_asgi_target_hidden_imports(),
        *_collect_migration_hidden_imports(),
        *_collect_dynamic_import_hidden_imports(),
    ]
    hidden_imports = sorted(set(hidden_imports))
    run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--onedir" if packaging_mode == "onedir" else "--onefile",
            "--clean",
            # --clean wipes the WORK directory, not the dist directory. Without
            # --noconfirm, a dist path left behind by a different packaging mode
            # stops the build dead: an --onedir run creates
            # pyinstaller-dist/circuit-breaker as a DIRECTORY, and the next
            # --onefile build then fails with "The output directory ... is not
            # empty" because it wants to write a FILE of that name. Found by
            # running a normal build in a tree where the packaging benchmark had
            # run once — which is every developer's tree after step 4.
            "--noconfirm",
            "--distpath",
            str(dist_dir),
            "--workpath",
            str(build_dir),
            "--specpath",
            str(spec_dir),
            # `circuit-breaker --version` printed "unknown" from every installed
            # package. resolve_app_version() looks for a VERSION file beside the
            # executable (share/VERSION, the tarball bundle layout) or inside the
            # frozen bundle — but nothing ever put one inside the bundle, and a
            # packaged install relocates the binary to /usr/local/bin while its
            # share/ tree goes to /usr/local/share/circuit-breaker, so the
            # adjacent-share candidate resolves to a path that does not exist.
            # Shipping the file inside the binary makes the version travel with
            # the executable regardless of how the package lays the rest out.
            # It is the same REPO_ROOT/VERSION that stage_bundle() copies to
            # share/VERSION, so the embedded and shipped copies cannot disagree.
            "--add-data",
            f"{VERSION_FILE}{os.pathsep}.",
            "--name",
            binary_name(target_os),
            *[f"--hidden-import={m}" for m in hidden_imports],
            str(BACKEND_ENTRYPOINT),
        ]
    )
    if packaging_mode == "onedir":
        # PyInstaller emits dist/<name>/<name> plus dist/<name>/_internal/.
        binary_path = dist_dir / binary_name(target_os) / binary_name(target_os)
    else:
        binary_path = dist_dir / binary_name(target_os)
    if not binary_path.exists():
        raise SystemExit(f"Expected PyInstaller output missing: {binary_path}")
    assert_binary_contains_application(binary_path)
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
    if binary.startswith("bin/"):
        contents_lines = (
            f"  python/                 — bundled CPython (python-build-standalone) and site-packages\n"
            f"  bin/circuit-breaker     — launcher\n"
            f"  README.txt              — This file\n"
            f"  .env.example            — Environment variable template\n"
            f"  manifest.json           — Build metadata (version, arch, checksums)\n"
            f"  share/VERSION           — Version string\n"
            f"  share/frontend/         — Pre-built web UI assets\n"
            f"  share/backend/alembic.ini — Database migration config\n"
            f"  share/backend/migrations/ — Database migration scripts\n"
            f"  share/config.toml.default — Sample configuration file\n"
        )
    else:
        contents_lines = (
            f"  {binary}                  — Application binary\n"
            f"  README.txt                — This file\n"
            f"  .env.example              — Environment variable template\n"
            f"  manifest.json             — Build metadata (version, arch, checksums)\n"
            f"  share/VERSION             — Version string\n"
            f"  share/frontend/           — Pre-built web UI assets\n"
            f"  share/backend/alembic.ini — Database migration config\n"
            f"  share/backend/migrations/ — Database migration scripts\n"
            f"  share/config.toml.default — Sample configuration file\n"
        )
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
{contents_lines}
Full documentation
-------------------
  https://github.com/BlkLeg/circuitbreaker
"""
    (bundle_dir / "README.txt").write_text(text, encoding="utf-8")


def _write_build_info(share_dir: Path, version: str, target_os: str, target_arch: str) -> None:
    """Record where and on what this package was built, inside the package.

    A PyInstaller bundle inherits the glibc floor of its
    build host: built on Fedora 44 it demands GLIBC_2.38 and will not run on
    Debian 12, while the release job builds on ubuntu-22.04 whose 2.35 floor
    every supported distro clears. So a locally built package and the released
    one are genuinely different artifacts, and a verification tier that cannot
    tell them apart will happily bank evidence on the one nobody installs.

    Written into share/ rather than beside the package so it travels *inside*
    the artifact: the claim is then read from the thing under test rather than
    from the directory someone found it in.
    """
    try:
        glibc = platform.libc_ver()[1] or "unknown"
    except OSError:  # pragma: no cover - libc_ver probes the executable
        glibc = "unknown"

    distro = "unknown"
    os_release = Path("/etc/os-release")
    if os_release.is_file():
        fields = {}
        for line in os_release.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            fields[key] = value.strip().strip('"')
        distro = f"{fields.get('ID', 'unknown')}-{fields.get('VERSION_ID', '')}".rstrip("-")

    # GITHUB_ACTIONS is set to "true" by the runner and by nothing else; a local
    # build that wants to claim CI provenance has to lie on purpose.
    in_ci = os.environ.get("GITHUB_ACTIONS", "").lower() == "true"
    info = {
        "version": version,
        "os": target_os,
        "arch": target_arch,
        "built_by": "ci" if in_ci else "local",
        "glibc": glibc,
        "distro": distro,
        "python": platform.python_version(),
        "ci_run": os.environ.get("GITHUB_RUN_ID", ""),
        "ci_workflow": os.environ.get("GITHUB_WORKFLOW", ""),
        "commit": os.environ.get("GITHUB_SHA", ""),
    }
    # Trailing newline: the tier cats this file into its log, and without one the
    # next line starts on the same row as the closing brace.
    (share_dir / "build-info.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")


# Build-host bytecode never belongs in a release artifact: it is compiled by
# whatever interpreter ran this script, so it is stale for any target on a
# different Python and is read by nothing that ships here.
_NO_BYTECODE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")


def stage_bundle(
    binary_path: Path,
    version: str,
    target_os: str,
    target_arch: str,
    frontend_dir: Path,
    work_dir: Path,
    packaging_mode: str = "onefile",
    tree: Path | None = None,
) -> tuple[Path, dict[str, object]]:
    bundle_dir = work_dir / f"bundle-{target_os}-{target_arch}"
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    share_dir = bundle_dir / "share"
    backend_share = share_dir / "backend"
    frontend_share = share_dir / "frontend"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    backend_share.mkdir(parents=True, exist_ok=True)

    if packaging_mode == "pbs":
        if tree is None:
            raise SystemExit("stage_bundle(packaging_mode='pbs') needs the tree from pbs_tree.build_tree")
        # The tree already carries python/, bin/, share/{VERSION,build-info.json,
        # backend/,frontend/} and agent-binaries/. Copied whole, symlinks
        # preserved (python/bin/python3 -> python3.12), and nothing below may
        # rewrite share/build-info.json: its runtime_digest is what the mono
        # image is held equal to.
        shutil.rmtree(bundle_dir)
        shutil.copytree(tree, bundle_dir, symlinks=True)
        share_dir.mkdir(exist_ok=True)
    else:
        if packaging_mode == "onedir":
            for item in binary_path.parent.iterdir():
                destination = bundle_dir / item.name
                if item.is_dir():
                    shutil.copytree(item, destination, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, destination)
        else:
            shutil.copy2(binary_path, bundle_dir / binary_path.name)
        shutil.copy2(VERSION_FILE, share_dir / "VERSION")
        _write_build_info(share_dir, version, target_os, target_arch)
        shutil.copy2(BACKEND_ROOT / "alembic.ini", backend_share / "alembic.ini")
        shutil.copytree(
            BACKEND_ROOT / "migrations",
            backend_share / "migrations",
            dirs_exist_ok=True,
            ignore=_NO_BYTECODE,
        )
        shutil.copytree(frontend_dir, frontend_share, dirs_exist_ok=True)
    shutil.copy2(DOCS_SEED_FILE, share_dir / "DocsPage.md")

    agent_binaries_src = work_dir / "agent-dist"
    if agent_binaries_src.exists() and not (bundle_dir / "agent-binaries").exists():
        shutil.copytree(agent_binaries_src, bundle_dir / "agent-binaries", dirs_exist_ok=True)

    # Bundle config.toml template if present
    config_default = REPO_ROOT / "packaging" / "config.toml.default"
    if config_default.exists():
        shutil.copy2(config_default, share_dir / "config.toml.default")

    # Bundle launchd plist template if present
    plist_template = REPO_ROOT / "packaging" / "com.blkleg.circuitbreaker.plist"
    if plist_template.exists():
        shutil.copy2(plist_template, share_dir / "com.blkleg.circuitbreaker.plist")

    # The NATS pin, unguarded: deploy/setup.sh reads it to learn which broker
    # version to fetch and which digest to check, and aborts the install when it
    # cannot find one. Every other packaging/ file above is optional and copied
    # `if exists`; this one is load-bearing for the tarball install path, so a
    # missing pin must break the build here rather than ship a tarball that dies
    # on the user's host at "Cannot find packaging/nats-server.pin".
    #
    # It goes in share/ rather than a new top-level packaging/ because share/ is
    # already the directory install.sh copies wholesale into /opt/circuitbreaker.
    # A bundle-only packaging/ would land nowhere: stage0_install_bundle copies
    # the subdirectories it names and no others.
    shutil.copy2(REPO_ROOT / "packaging" / "nats-server.pin", share_dir / "nats-server.pin")

    # Bundle installer infrastructure for curl-pipe / Proxmox installs
    deploy_src = REPO_ROOT / "deploy"
    deploy_dst = bundle_dir / "deploy"
    for subdir in ("config", "systemd", "nginx", "cli", "misc", "scripts", "helper", "lib"):
        src = deploy_src / subdir
        if src.exists():
            shutil.copytree(src, deploy_dst / subdir, dirs_exist_ok=True, ignore=_NO_BYTECODE)
    shutil.copy2(deploy_src / "setup.sh", deploy_dst / "setup.sh")
    installer_src = REPO_ROOT / "install.sh"
    if installer_src.exists():
        shutil.copy2(installer_src, bundle_dir / "install.sh")

    # The uninstaller travels with the bundle for the same reason the installer
    # does. Without it, `cb uninstall` on a native install found neither
    # /usr/local/bin/uninstall-circuit-breaker nor a sibling uninstall.sh and
    # told the operator to "run it from a checkout" — on a host that was
    # installed from a tarball and has no checkout. deploy/setup.sh installs
    # this copy to /usr/local/bin/uninstall-circuit-breaker, which is the first
    # path `cb uninstall` looks for.
    uninstaller_src = REPO_ROOT / "uninstall.sh"
    if uninstaller_src.exists():
        shutil.copy2(uninstaller_src, bundle_dir / "uninstall.sh")

    manifest = {
        "app": "Circuit Breaker",
        "version": version,
        "os": target_os,
        "arch": target_arch,
        "archive": archive_name(version, target_os, target_arch),
        "binary": "bin/circuit-breaker" if packaging_mode == "pbs" else binary_path.name,
        "runtime": "pbs" if packaging_mode == "pbs" else "pyinstaller",
        "share_dir": "share",
        "resources": {
            "version": "share/VERSION",
            "docs_seed": "share/DocsPage.md",
            "frontend": "share/frontend",
            "alembic_ini": "share/backend/alembic.ini",
            "migrations": "share/backend/migrations",
            "nats_pin": "share/nats-server.pin",
            "deploy": "deploy",
            "installer": "install.sh",
            "uninstaller": "uninstall.sh",
            "agent_binaries": "agent-binaries",
        },
    }
    (bundle_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    _write_readme(bundle_dir, version, target_os, str(manifest["binary"]))
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
                # recursive=False is load-bearing. tarfile.add() recurses into a
                # directory by default, so adding every rglob result — which
                # includes directories — wrote each subtree once for the
                # directory and then again, entry by entry, as the loop reached
                # its children. Nested directories compounded it: the v0.4.3
                # bundle carried 4012 members for 864 distinct paths, every
                # duplicate a second compressed copy of the same bytes. It
                # extracted correctly only because the later copy happened to
                # overwrite the earlier one. The ZipFile branch above never had
                # the bug because it skips anything that is not a file; this
                # keeps the directory entries and adds each exactly once.
                archive.add(
                    file_path,
                    arcname=file_path.relative_to(bundle_dir),
                    recursive=False,
                )
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


def stage_nats_server(bundle_dir: Path, target_arch: str) -> str:
    """Download the pinned NATS server into the bundle, verifying its digest.

    Only Fedora needs this: Debian/Ubuntu and Alpine package nats-server, so
    nfpm.yaml depends on the distro package there and the distro owns CVE
    updates. Fedora packages none, so the circuit-breaker-nats package vendors
    this binary.

    Fails rather than skips. A build that quietly omits the broker produces an
    rpm that installs and cannot start, which is the exact defect Tier 3 caught
    and the reason this code path exists.

    Returns the pinned version string.
    """
    pin_path = REPO_ROOT / "packaging" / "nats-server.pin"
    pin: dict[str, str] = {}
    for line in pin_path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if "=" in line:
            key, _, value = line.partition("=")
            pin[key.strip()] = value.strip()

    version = pin["NATS_VERSION"]
    digest = pin.get(f"NATS_SHA256_{target_arch}")
    if not digest:
        raise RuntimeError(
            f"packaging/nats-server.pin has no NATS_SHA256_{target_arch}; add the "
            f"digest from the release's SHA256SUMS before building for this arch"
        )

    tarball = f"nats-server-v{version}-linux-{target_arch}.tar.gz"
    url = f"https://github.com/nats-io/nats-server/releases/download/v{version}/{tarball}"

    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / tarball
        print(f"  Fetching {tarball}")
        urllib.request.urlretrieve(url, archive)

        actual = hashlib.sha256(archive.read_bytes()).hexdigest()
        if actual != digest:
            raise RuntimeError(
                f"NATS checksum mismatch for {tarball}:\n"
                f"  expected {digest}\n  actual   {actual}\n"
                f"Refusing to package an unverified binary."
            )

        with tarfile.open(archive) as tar:
            member = next(
                (m for m in tar.getmembers() if m.name.endswith("/nats-server")), None
            )
            if member is None:
                raise RuntimeError(f"no nats-server binary inside {tarball}")
            member.name = "nats-server"
            nats_dir = bundle_dir / "nats"
            nats_dir.mkdir(parents=True, exist_ok=True)
            tar.extract(member, nats_dir, filter="data")
        (bundle_dir / "nats" / "nats-server").chmod(0o755)

    print(f"  Staged nats-server v{version} ({target_arch}), digest verified")
    return version


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

    # Symlink bundle contents to where nfpm.yaml expects them.
    # symlinks=True is load-bearing for --packaging pbs: the tree's
    # python/bin/python3 -> python3.12 (and friends) must stay symlinks so
    # runtime_digest of dist/native/bundle matches the tree that wrote it.
    dist_bundle = REPO_ROOT / "dist" / "native" / "bundle"
    if dist_bundle.exists():
        shutil.rmtree(dist_bundle)
    shutil.copytree(bundle_dir, dist_bundle, symlinks=True)

    env = {
        **os.environ,
        "VERSION": version,
        "GOARCH": goarch,
    }

    packages: list[Path] = []

    # The vendored broker, for distros that package none. Staged and
    # digest-verified first: a failure here must stop the build rather than
    # produce a package whose companion silently does not exist.
    # dist_bundle, not bundle_dir: this function copies bundle_dir into
    # dist/native/bundle above, and nfpm-nats.yaml reads the dist path. Staging
    # into the source bundle after that copy puts the binary somewhere nothing
    # packages from.
    #
    # Built as BOTH rpm and deb, which it was not. The premise for deb-only-
    # relying-on-the-distro was "Debian/Ubuntu ship nats-server", and that is
    # true of Debian 12 and Ubuntu 24.04 and false of Ubuntu 22.04 — which
    # packages no nats-server at all. The application deb hard-depended on it,
    # so the package was uninstallable on a current Ubuntu LTS and the release
    # gate caught it only at Artifact Smoke, after everything else was built.
    # A companion that exists for one packager and not the other is a fallback
    # that is only nominally available.
    nats_version = stage_nats_server(dist_bundle, goarch)
    nats_config = REPO_ROOT / "packaging" / "nfpm-nats.yaml"
    for nats_fmt in ("rpm", "deb"):
        nats_pkg = output_dir / f"circuit-breaker-nats_{nats_version}_{goarch}.{nats_fmt}"
        nats_result = subprocess.run(
            [nfpm, "package", "--config", str(nats_config), "--packager", nats_fmt,
             "--target", str(nats_pkg)],
            env={**env, "NATS_VERSION": nats_version}, cwd=str(REPO_ROOT),
            capture_output=True, text=True,
        )
        if nats_result.returncode != 0:
            raise RuntimeError(
                f"circuit-breaker-nats {nats_fmt} packaging failed: "
                f"{nats_result.stderr.strip()}"
            )
        print(f"  Created: {nats_pkg.name}")
        packages.append(nats_pkg)

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

    app_root = appdir / "usr" / "lib" / "circuitbreaker"
    app_root.parent.mkdir(parents=True)
    for name in ("python", "bin", "share", "agent-binaries"):
        source = bundle_dir / name
        if source.exists():
            shutil.copytree(source, app_root / name, symlinks=True)
    apprun = appdir / "AppRun"
    apprun.write_text(
        '#!/bin/sh\n'
        'here="$(dirname "$(readlink -f "$0")")"\n'
        'export CB_AGENT_BINARIES_DIR="$here/usr/lib/circuitbreaker/agent-binaries"\n'
        'exec "$here/usr/lib/circuitbreaker/bin/circuit-breaker" "$@"\n'
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
        # Fatal for the same reason the Arch failure above is: appimagetool was
        # present and was run. The AppImage is a published release asset (it is
        # attached to every release since 0.3.9), so a build that drops it and
        # exits 0 produces a release whose asset list is quietly short.
        raise SystemExit(
            "AppImage creation failed after appimagetool was found and invoked.\n"
            f"  stderr: {result.stderr.strip()}"
        )


def create_arch_package(
    bundle_dir: Path, version: str, target_arch: str, output_dir: Path, tarball_path: Path
) -> Path | None:
    """Generate .pkg.tar.zst using makepkg with a local-source patched PKGBUILD."""
    makepkg = shutil.which("makepkg")
    if not makepkg:
        print("makepkg not found — skipping Arch package generation.")
        return None

    # makepkg being on PATH is not the same as makepkg being usable. It shells
    # out to fakeroot for the packaging step, and a machine that has pacman
    # tooling without it — which is most non-Arch machines that have either —
    # fails with "Cannot find the fakeroot binary" after doing all the work.
    #
    # That belongs on the skip side of the line, not the fatal side. The rule
    # this function follows is: a toolchain that cannot run is a format this
    # machine cannot produce, and a toolchain that runs and fails is a defect.
    # Conflating them would turn a missing optional dependency into a broken
    # build, which is how a fail-closed rule gets deleted rather than obeyed.
    missing_helpers = [tool for tool in ("fakeroot", "bsdtar") if shutil.which(tool) is None]
    if missing_helpers:
        print(
            f"makepkg found but {', '.join(missing_helpers)} missing — "
            "skipping Arch package generation."
        )
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

    # PKGBUILD's `install=` names a .install hook file, and makepkg resolves it
    # relative to the PKGBUILD's own directory — which is this work_dir, not the
    # repo root. Without this copy every invocation died before packaging with
    # "install file (circuit-breaker.install) does not exist or is not a regular
    # file", and the failure was a WARNING that left the build exiting 0. The
    # result: this function has never once produced a package on any machine
    # that had makepkg, and nothing said so.
    install_hook = re.search(r'^install=(\S+)', patched, flags=re.MULTILINE)
    if install_hook:
        hook_src = REPO_ROOT / install_hook.group(1)
        if not hook_src.exists():
            raise SystemExit(
                f"PKGBUILD declares install={install_hook.group(1)}, which does not "
                f"exist at {hook_src}"
            )
        shutil.copy2(hook_src, work_dir / hook_src.name)

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

    # Attempted and failed is fatal; absent toolchain is a skip. The two used
    # to print the same shape of message and both left the build exiting 0,
    # which is how `.pkg.tar.zst` came to be claimed as produced (ADR 0005,
    # Tier 3) while no release has ever carried one. A silent success fallback
    # is exactly what CLAUDE.md's "no placeholders / fail closed" rule is for:
    # if makepkg is here, it runs, and if it fails the build stops.
    if result.returncode != 0:
        raise SystemExit(
            "Arch package creation failed after makepkg was found and invoked.\n"
            f"  exit status: {result.returncode}\n"
            f"  stderr: {result.stderr.strip()}\n"
            "Install a working makepkg or remove PKGBUILD; do not ship a build "
            "that silently drops a format."
        )

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
    output_dir = args.output_dir
    work_dir = REPO_ROOT / "build" / "native-release" / f"{target_os}-{target_arch}"
    frontend_dir = FRONTEND_DIST

    ensure_frontend_dist(frontend_dir)
    if args.clean and work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    if target_os == "linux":
        ensure_go_available()
        build_agent_binaries(version, work_dir)
    if args.packaging == "pbs":
        if target_os != "linux":
            raise SystemExit("--packaging pbs targets Linux only; python-build-standalone pins exist for linux/amd64 and linux/arm64")
        tree = pbs_tree.build_tree(
            arch=target_arch,
            version=version,
            output=work_dir / "app",
            cache_dir=REPO_ROOT / "build" / "pbs-cache",
            frontend_dist=frontend_dir,
            agent_dist=work_dir / "agent-dist",
        )
        bundle_dir, manifest = stage_bundle(
            binary_path=tree / "bin" / "circuit-breaker",
            version=version,
            target_os=target_os,
            target_arch=target_arch,
            frontend_dir=frontend_dir,
            work_dir=work_dir,
            packaging_mode="pbs",
            tree=tree,
        )
    else:
        ensure_pyinstaller_available()
        binary_path = build_binary(target_os, work_dir, args.packaging)
        bundle_dir, manifest = stage_bundle(
            binary_path=binary_path,
            version=version,
            target_os=target_os,
            target_arch=target_arch,
            frontend_dir=frontend_dir,
            work_dir=work_dir,
            packaging_mode=args.packaging,
        )
    archive_path = create_archive(bundle_dir, version, target_os, target_arch, output_dir)
    write_metadata(output_dir, manifest, archive_path)
    print(archive_path)

    # nfpm / AppImage / Arch wrap the PBS tree layout. --packaging onefile still
    # stages a tarball (journey --previous leg) but must not run those wrappers
    # against a PyInstaller bundle.
    if target_os == "linux" and args.packaging == "pbs":
        create_linux_packages(bundle_dir, version, target_arch, output_dir)
        create_appimage(bundle_dir, version, target_arch, output_dir)
        create_arch_package(bundle_dir, version, target_arch, output_dir, archive_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
