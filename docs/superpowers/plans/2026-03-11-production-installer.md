# Production Image & Installer Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Circuit Breaker installable as a production-grade native application on Linux (deb/rpm/tar.gz), macOS (tar.gz/launchd), and Windows (zip), with auto-update, config.toml support, and a CI pipeline that builds and publishes all artifacts on every tagged release.

**Architecture:** The existing `install.sh` (68.8 KB) is already a comprehensive 3-mode installer (Docker / Compose / Native Binary). This plan fixes broken paths, adds Linux packaging (deb/rpm via nfpm), macOS/Windows platform support, a `native.yml` GitHub Actions workflow, auto-update checks, and optional `config.toml` configuration. The PyInstaller-based binary build (`scripts/build_native_release.py`) is retained as the packaging backend.

**Tech Stack:** Bash (installer), Python 3.12 + PyInstaller (binary), nfpm (deb/rpm), GitHub Actions (CI), TOML (config)

**Key Architecture Constraint:** The app requires PostgreSQL + Redis + NATS at runtime. The Docker mono image embeds all three. Native binary mode requires the user to provide these services externally (or use the mono image). The installer must make this clear and guide the user through dependency setup.

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `nfpm.yaml` | nfpm config for generating .deb and .rpm packages |
| `packaging/postinstall.sh` | Post-install script for deb/rpm (create user, dirs, enable service) |
| `packaging/preremove.sh` | Pre-remove script for deb/rpm (stop service) |
| `packaging/circuit-breaker.service` | Canonical systemd unit file (shared by all Linux install paths) |
| `packaging/com.blkleg.circuitbreaker.plist` | macOS launchd agent plist |
| `packaging/config.toml.default` | Default config.toml template with all options documented |
| `.github/workflows/native.yml` | CI: build native binaries + packages for all platforms on v* tags |
| `apps/backend/src/app/core/config_toml.py` | TOML config loader (reads config.toml → sets env vars) |
| `apps/backend/src/app/core/update_check.py` | GitHub Releases API check on startup |

### Modified Files
| File | Change |
|------|--------|
| `install.sh` | Fix compose mode (docker-compose.prod.yml → docker-compose.yml); add macOS launchd support; add dependency guidance for native mode |
| `scripts/build_native_release.py` | Add nfpm invocation for deb/rpm; add macOS .tar.gz with plist; bundle config.toml.default |
| `.github/workflows/release.yml` | Trigger native.yml; upload artifacts to release |
| `Makefile` | Add `deb`, `rpm`, `package-all` targets |
| `apps/backend/src/app/start.py` | Load config.toml before env; trigger update check |
| `uninstall.sh` | Add native binary + macOS cleanup paths |

---

## Chunk 1: Fix Broken Paths & Harden Existing Installer

### Task 1: Fix Compose Mode — Replace Deleted docker-compose.prod.yml Reference

The Compose install mode in `install.sh` downloads `docker-compose.prod.yml` from GitHub, but that file was deleted. The canonical compose file is now `docker/docker-compose.yml`.

**Files:**
- Modify: `install.sh:1571-1575` (Install_Compose_Mode download URLs)
- Modify: `install.sh:1586-1600` (compose -f references)
- Modify: `install.sh:1633-1655` (Setup_Systemd_Compose unit file)

- [ ] **Step 1: Identify all references to docker-compose.prod.yml in install.sh**

Run: `grep -n 'docker-compose.prod.yml\|compose.prod' install.sh`

Document every line number that needs changing.

- [ ] **Step 2: Replace download URL**

In `Install_Compose_Mode()`, change:
```bash
# OLD
cb_fetch "${base}/docker/docker-compose.prod.yml" "$CB_INSTALL_DIR/docker-compose.prod.yml" 0 \
  || Show 1 "Failed to download docker-compose.prod.yml"
# NEW
cb_fetch "${base}/docker/docker-compose.yml" "$CB_INSTALL_DIR/docker-compose.yml" 0 \
  || Show 1 "Failed to download docker-compose.yml"
```

- [ ] **Step 3: Update all `docker compose -f` references**

Replace every `docker-compose.prod.yml` with `docker-compose.yml` in:
- `Install_Compose_Mode()` pull and up commands
- `Setup_Systemd_Compose()` ExecStart/ExecStop/ExecReload lines
- `Save_Install_Config_Compose()` if it references the filename

- [ ] **Step 4: Verify compose file is self-contained for remote download**

The current `docker/docker-compose.yml` uses `build: context: ..` which won't work when downloaded standalone. The installer must override this to use the prebuilt image only.

Add after download:
```bash
# Ensure compose uses prebuilt image (not local build context)
sed -i '/build:/,/dockerfile:/d' "$CB_INSTALL_DIR/docker-compose.yml"
```

Or better: download a stripped version. Create a sed pipeline that removes the `build:` block and ensures `image:` is present (it already is in the current file).

- [ ] **Step 5: Test compose mode end-to-end**

Run: `CB_MODE=compose CB_YES=1 bash install.sh --dry-run` (if dry-run exists, otherwise manual test)

Verify: Downloads succeed, compose up works, systemd unit references correct file.

- [ ] **Step 6: Commit**

```bash
git add install.sh
git commit -m "fix: compose install mode references deleted docker-compose.prod.yml

Update Install_Compose_Mode to use docker/docker-compose.yml (the canonical
compose file) instead of the deleted docker-compose.prod.yml. Strip build
context from downloaded compose file so it uses the prebuilt GHCR image."
```

---

### Task 2: Add Native Mode Dependency Guidance

The native binary mode requires external PostgreSQL + Redis + NATS, but the installer doesn't explain this. Users who choose native mode need to know what to install first.

**Files:**
- Modify: `install.sh` — `Install_Binary_Mode()` function (around line 1720)
- Modify: `install.sh` — `Prompt_Mode()` function (around line 1486)

- [ ] **Step 1: Add dependency check to Install_Binary_Mode()**

After the section header, before `Require_Sudo`, add:
```bash
  # ── Service dependency check ──
  echo -e "  ${aCOLOUR[4]}Native mode requires external services:${COLOUR_RESET}"
  echo -e "  ${GREEN_BULLET} PostgreSQL 15+  ${aCOLOUR[2]}(data store)${COLOUR_RESET}"
  echo -e "  ${GREEN_BULLET} Redis 7+        ${aCOLOUR[2]}(telemetry cache)${COLOUR_RESET}"
  echo -e "  ${GREEN_BULLET} NATS 2.10+      ${aCOLOUR[2]}(message bus)${COLOUR_RESET}"
  echo ""
  echo -e "  ${aCOLOUR[2]}If you want everything bundled, choose Docker mode instead.${COLOUR_RESET}"
  echo ""

  # Check if PostgreSQL is reachable
  if command -v pg_isready >/dev/null 2>&1 && pg_isready -q 2>/dev/null; then
    Show 0 "PostgreSQL is reachable."
  else
    Show 3 "PostgreSQL not detected. You'll need to configure CB_DB_URL after install."
  fi
```

- [ ] **Step 2: Update Prompt_Mode description for native option**

Change:
```bash
echo -e "  ${aCOLOUR[1]}[3]${COLOUR_RESET} Native binary    ${aCOLOUR[2]}(systemd service, FHS paths, no Docker required)${COLOUR_RESET}"
```
To:
```bash
echo -e "  ${aCOLOUR[1]}[3]${COLOUR_RESET} Native binary    ${aCOLOUR[2]}(systemd service — requires external Postgres/Redis/NATS)${COLOUR_RESET}"
```

- [ ] **Step 3: Commit**

```bash
git add install.sh
git commit -m "feat: add dependency guidance for native binary install mode

Inform users that native mode requires external PostgreSQL, Redis, and NATS.
Check for PostgreSQL availability and warn if not found. Update mode prompt
to clarify the requirement."
```

---

## Chunk 2: Linux Packaging (deb/rpm via nfpm)

### Task 3: Create Canonical systemd Unit File

Extract the systemd unit from install.sh into a standalone file that can be shared by the installer, deb/rpm post-install, and documentation.

**Files:**
- Create: `packaging/circuit-breaker.service`

- [ ] **Step 1: Create the packaging directory**

```bash
mkdir -p packaging
```

- [ ] **Step 2: Write the systemd unit file**

Create `packaging/circuit-breaker.service`:
```ini
[Unit]
Description=Circuit Breaker — Homelab Topology Mapper
Documentation=https://github.com/BlkLeg/circuitbreaker
After=network-online.target postgresql.service redis.service nats.service
Wants=network-online.target

[Service]
Type=exec
User=circuitbreaker
Group=circuitbreaker
ExecStart=/usr/local/bin/circuit-breaker serve
ExecReload=/bin/kill -HUP $MAINPID
Restart=on-failure
RestartSec=5
TimeoutStartSec=30
TimeoutStopSec=30

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/var/lib/circuit-breaker /var/log/circuit-breaker /etc/circuit-breaker
PrivateTmp=true
ProtectKernelTunables=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LimitNOFILE=65536

# Environment
EnvironmentFile=-/etc/circuit-breaker/circuit-breaker.env

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 3: Commit**

```bash
git add packaging/circuit-breaker.service
git commit -m "feat: add canonical systemd unit file for native binary mode

Hardened systemd unit with ProtectSystem=strict, NoNewPrivileges, PrivateTmp.
Reads env from /etc/circuit-breaker/circuit-breaker.env. Used by deb/rpm
post-install and install.sh native mode."
```

---

### Task 4: Create deb/rpm Post-Install and Pre-Remove Scripts

**Files:**
- Create: `packaging/postinstall.sh`
- Create: `packaging/preremove.sh`

- [ ] **Step 1: Write postinstall.sh**

```bash
#!/bin/bash
set -e

# Create system user if it doesn't exist
if ! id -u circuitbreaker >/dev/null 2>&1; then
  useradd --system --no-create-home --shell /usr/sbin/nologin \
    --home-dir /var/lib/circuit-breaker circuitbreaker
fi

# Create directories
mkdir -p /var/lib/circuit-breaker /var/log/circuit-breaker /etc/circuit-breaker
chown circuitbreaker:circuitbreaker /var/lib/circuit-breaker /var/log/circuit-breaker
chmod 750 /var/lib/circuit-breaker /var/log/circuit-breaker
chmod 755 /etc/circuit-breaker

# Install default config if not present
if [ ! -f /etc/circuit-breaker/config.toml ]; then
  cp /usr/local/share/circuit-breaker/config.toml.default \
     /etc/circuit-breaker/config.toml
  chmod 640 /etc/circuit-breaker/config.toml
  chown root:circuitbreaker /etc/circuit-breaker/config.toml
fi

# Generate env file with secrets if not present
if [ ! -f /etc/circuit-breaker/circuit-breaker.env ]; then
  VAULT_KEY=$(openssl rand -base64 32)
  cat > /etc/circuit-breaker/circuit-breaker.env <<EOF
# Circuit Breaker environment — auto-generated during install
CB_DB_URL=postgresql://circuitbreaker:changeme@127.0.0.1:5432/circuitbreaker
CB_VAULT_KEY=${VAULT_KEY}
CB_REDIS_URL=redis://127.0.0.1:6379/0
NATS_AUTH_TOKEN=$(openssl rand -hex 16)
STATIC_DIR=/usr/local/share/circuit-breaker/frontend
CB_ALEMBIC_INI=/usr/local/share/circuit-breaker/backend/alembic.ini
EOF
  chmod 600 /etc/circuit-breaker/circuit-breaker.env
  chown root:circuitbreaker /etc/circuit-breaker/circuit-breaker.env
fi

# Enable and reload systemd
systemctl daemon-reload
systemctl enable circuit-breaker.service

echo ""
echo "Circuit Breaker installed successfully."
echo ""
echo "  Next steps:"
echo "    1. Edit /etc/circuit-breaker/circuit-breaker.env"
echo "       - Set CB_DB_URL to your PostgreSQL connection string"
echo "       - Ensure PostgreSQL, Redis, and NATS are running"
echo "    2. sudo systemctl start circuit-breaker"
echo "    3. Open http://localhost:8080"
echo ""
```

- [ ] **Step 2: Write preremove.sh**

```bash
#!/bin/bash
set -e

# Stop and disable service
if systemctl is-active --quiet circuit-breaker.service 2>/dev/null; then
  systemctl stop circuit-breaker.service
fi
if systemctl is-enabled --quiet circuit-breaker.service 2>/dev/null; then
  systemctl disable circuit-breaker.service
fi
systemctl daemon-reload 2>/dev/null || true
```

- [ ] **Step 3: Make scripts executable and commit**

```bash
chmod +x packaging/postinstall.sh packaging/preremove.sh
git add packaging/postinstall.sh packaging/preremove.sh
git commit -m "feat: add deb/rpm post-install and pre-remove scripts

Post-install creates circuitbreaker user, directories, default config,
and enables the systemd service. Pre-remove stops and disables cleanly."
```

---

### Task 5: Create nfpm Configuration

nfpm generates .deb and .rpm packages from a YAML config without requiring dpkg-deb or rpmbuild. It's a single Go binary available in GitHub Actions.

**Files:**
- Create: `nfpm.yaml`

- [ ] **Step 1: Write nfpm.yaml**

```yaml
name: circuit-breaker
arch: "${GOARCH}"  # Set by CI: amd64 or arm64
platform: linux
version: "${VERSION}"  # Set by CI from VERSION file
version_schema: semver
maintainer: "BlkLeg <admin@circuitbreaker.io>"
description: "Circuit Breaker — Homelab topology mapper and network documentation tool"
vendor: "BlkLeg"
homepage: "https://github.com/BlkLeg/circuitbreaker"
license: "MIT"
section: "admin"
priority: "optional"

contents:
  # Binary
  - src: dist/native/bundle/circuit-breaker
    dst: /usr/local/bin/circuit-breaker
    file_info:
      mode: 0755

  # Frontend static files
  - src: dist/native/bundle/share/frontend/
    dst: /usr/local/share/circuit-breaker/frontend/
    type: tree

  # Backend migrations + alembic config
  - src: dist/native/bundle/share/backend/
    dst: /usr/local/share/circuit-breaker/backend/
    type: tree

  # VERSION file
  - src: dist/native/bundle/share/VERSION
    dst: /usr/local/share/circuit-breaker/VERSION

  # Default config template
  - src: packaging/config.toml.default
    dst: /usr/local/share/circuit-breaker/config.toml.default
    file_info:
      mode: 0644

  # systemd unit
  - src: packaging/circuit-breaker.service
    dst: /lib/systemd/system/circuit-breaker.service
    file_info:
      mode: 0644

  # Create empty dirs
  - dst: /var/lib/circuit-breaker
    type: dir
    file_info:
      mode: 0750
      owner: circuitbreaker
      group: circuitbreaker
  - dst: /var/log/circuit-breaker
    type: dir
    file_info:
      mode: 0750
      owner: circuitbreaker
      group: circuitbreaker
  - dst: /etc/circuit-breaker
    type: dir
    file_info:
      mode: 0755

scripts:
  postinstall: packaging/postinstall.sh
  preremove: packaging/preremove.sh

overrides:
  deb:
    depends:
      - libc6
    recommends:
      - postgresql
      - redis-server
      - nats-server
  rpm:
    depends:
      - glibc
    recommends:
      - postgresql-server
      - redis
      - nats-server
```

- [ ] **Step 2: Commit**

```bash
git add nfpm.yaml
git commit -m "feat: add nfpm config for deb/rpm package generation

Packages the PyInstaller binary, frontend dist, migrations, systemd unit,
and default config into .deb/.rpm. Recommends (not requires) PostgreSQL,
Redis, and NATS as dependencies."
```

---

### Task 6: Create Default config.toml Template

**Files:**
- Create: `packaging/config.toml.default`

- [ ] **Step 1: Write config.toml.default**

```toml
# Circuit Breaker Configuration
# https://github.com/BlkLeg/circuitbreaker
#
# This file is read on startup. Environment variables override these values.
# After editing, restart the service: sudo systemctl restart circuit-breaker

[server]
# host = "0.0.0.0"
# port = 8080

[database]
# PostgreSQL connection URL (REQUIRED)
# url = "postgresql://circuitbreaker:changeme@127.0.0.1:5432/circuitbreaker"
#
# Connection pool settings (defaults are fine for most deployments)
# pool_size = 20
# max_overflow = 20

[redis]
# Redis URL for telemetry cache and pub/sub
# url = "redis://127.0.0.1:6379/0"

[nats]
# NATS URL and auth for the internal message bus
# url = "nats://127.0.0.1:4222"
# auth_token = ""

[security]
# Fernet encryption key for credential vault (auto-generated if empty)
# vault_key = ""
#
# CORS origins (comma-separated or JSON array)
# cors_origins = ""

[discovery]
# Docker socket path for container discovery
# docker_host = "/var/run/docker.sock"
#
# Proxmox API URL for VM/LXC discovery
# proxmox_url = ""

[paths]
# Override default file locations
# data_dir = "/var/lib/circuit-breaker"
# log_dir = "/var/log/circuit-breaker"
# static_dir = "/usr/local/share/circuit-breaker/frontend"
# alembic_ini = "/usr/local/share/circuit-breaker/backend/alembic.ini"

[updates]
# Check for new versions on startup (does NOT auto-install)
check_on_startup = true
```

- [ ] **Step 2: Commit**

```bash
git add packaging/config.toml.default
git commit -m "feat: add default config.toml template for native installs

Documents all configuration options with sensible defaults. Installed to
/usr/local/share/circuit-breaker/ and copied to /etc/circuit-breaker/ on
first install."
```

---

### Task 7: Update build_native_release.py to Invoke nfpm

**Files:**
- Modify: `scripts/build_native_release.py`

- [ ] **Step 1: Add nfpm packaging function**

After the existing `create_archive()` function, add:
```python
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

    packages = []
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
```

- [ ] **Step 2: Call it from main() after create_archive()**

```python
    archive_path = create_archive(bundle_dir, version, target_os, target_arch, output_dir)
    write_metadata(output_dir, manifest, archive_path)

    # Generate deb/rpm if on Linux
    if target_os == "linux":
        create_linux_packages(bundle_dir, version, target_arch, output_dir)
```

- [ ] **Step 3: Bundle config.toml.default in stage_bundle()**

Add to `stage_bundle()` after the existing shutil.copy2 calls:
```python
    config_default = REPO_ROOT / "packaging" / "config.toml.default"
    if config_default.exists():
        shutil.copy2(config_default, share_dir / "config.toml.default")
```

- [ ] **Step 4: Commit**

```bash
git add scripts/build_native_release.py
git commit -m "feat: generate deb/rpm packages via nfpm in native build

After creating the tar.gz archive, invoke nfpm to produce .deb and .rpm
packages. Bundles config.toml.default in the share directory. Gracefully
skips if nfpm is not installed."
```

---

### Task 8: Add Makefile Targets for Packaging

**Files:**
- Modify: `Makefile`

- [ ] **Step 1: Add packaging targets after build-native**

```makefile
deb: build-native ## Build .deb package (requires nfpm)
	@command -v nfpm >/dev/null || { echo "Install nfpm: https://nfpm.goreleaser.com/install/"; exit 1; }
	VERSION=$(VERSION) GOARCH=amd64 nfpm package --config nfpm.yaml --packager deb --target dist/native/
	@echo "deb package created in dist/native/"

rpm: build-native ## Build .rpm package (requires nfpm)
	@command -v nfpm >/dev/null || { echo "Install nfpm: https://nfpm.goreleaser.com/install/"; exit 1; }
	VERSION=$(VERSION) GOARCH=amd64 nfpm package --config nfpm.yaml --packager rpm --target dist/native/
	@echo "rpm package created in dist/native/"

package-all: build-native ## Build tar.gz + deb + rpm (requires nfpm)
	@echo "Building all native packages for $(OS_ARCH)..."
	@if command -v nfpm >/dev/null 2>&1; then \
		VERSION=$(VERSION) GOARCH=amd64 nfpm package --config nfpm.yaml --packager deb --target dist/native/; \
		VERSION=$(VERSION) GOARCH=amd64 nfpm package --config nfpm.yaml --packager rpm --target dist/native/; \
	else echo "nfpm not found — skipping deb/rpm. tar.gz still available in dist/native/"; fi
	@echo "Packages in dist/native/"
```

- [ ] **Step 2: Add to .PHONY**

Add `deb rpm package-all` to the existing `.PHONY` line for the RELEASE section.

- [ ] **Step 3: Commit**

```bash
git add Makefile
git commit -m "feat: add deb, rpm, package-all Makefile targets

Convenience targets that invoke nfpm after building the PyInstaller binary.
Falls back gracefully if nfpm is not installed."
```

---

## Chunk 3: GitHub Actions Native Build Pipeline

### Task 9: Create native.yml Workflow

This is the key missing piece — a CI workflow that builds native binaries and packages for all supported platforms on every tagged release, then uploads them to the GitHub Release.

**Files:**
- Create: `.github/workflows/native.yml`

- [ ] **Step 1: Write the workflow**

```yaml
name: Native Binaries

on:
  push:
    tags:
      - "v*"
  workflow_dispatch:
    inputs:
      version:
        description: "Version override (e.g. 0.2.2)"
        required: false

permissions:
  contents: write

jobs:
  build-linux:
    strategy:
      matrix:
        arch: [amd64, arm64]
        include:
          - arch: amd64
            runner: ubuntu-22.04
          - arch: arm64
            runner: ubuntu-22.04  # Cross-compile via PyInstaller in Docker
    runs-on: ${{ matrix.runner }}
    steps:
      - uses: actions/checkout@v4

      - name: Set version
        id: version
        run: |
          if [ -n "${{ inputs.version }}" ]; then
            echo "version=${{ inputs.version }}" >> "$GITHUB_OUTPUT"
          else
            echo "version=$(cat VERSION | tr -d '[:space:]')" >> "$GITHUB_OUTPUT"
          fi

      - name: Set up Python
        if: matrix.arch == 'amd64'
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Set up Node
        if: matrix.arch == 'amd64'
        uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: "npm"
          cache-dependency-path: apps/frontend/package-lock.json

      - name: Build frontend
        if: matrix.arch == 'amd64'
        run: |
          cd apps/frontend
          npm ci
          npm run build

      - name: Build native binary (amd64)
        if: matrix.arch == 'amd64'
        run: |
          python -m pip install --upgrade pip
          pip install -r apps/backend/requirements.txt
          pip install -r apps/backend/requirements-pg.txt
          pip install pyinstaller
          python scripts/build_native_release.py --clean

      - name: Build native binary (arm64 via Docker)
        if: matrix.arch == 'arm64'
        run: |
          make build-native-docker

      - name: Install nfpm
        run: |
          curl -sfL https://github.com/goreleaser/nfpm/releases/latest/download/nfpm_linux_amd64.tar.gz \
            | tar xz -C /usr/local/bin nfpm

      - name: Build deb/rpm packages
        run: |
          VERSION=${{ steps.version.outputs.version }} \
          GOARCH=${{ matrix.arch }} \
          nfpm package --config nfpm.yaml --packager deb --target dist/native/
          VERSION=${{ steps.version.outputs.version }} \
          GOARCH=${{ matrix.arch }} \
          nfpm package --config nfpm.yaml --packager rpm --target dist/native/

      - name: Upload artifacts
        uses: actions/upload-artifact@v4
        with:
          name: native-linux-${{ matrix.arch }}
          path: dist/native/*
          retention-days: 5

  build-macos:
    runs-on: macos-14  # Apple Silicon (arm64)
    steps:
      - uses: actions/checkout@v4

      - name: Set version
        id: version
        run: echo "version=$(cat VERSION | tr -d '[:space:]')" >> "$GITHUB_OUTPUT"

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: "npm"
          cache-dependency-path: apps/frontend/package-lock.json

      - name: Build frontend
        run: cd apps/frontend && npm ci && npm run build

      - name: Build native binary
        run: |
          python -m pip install --upgrade pip
          pip install -r apps/backend/requirements.txt
          pip install -r apps/backend/requirements-pg.txt
          pip install pyinstaller
          python scripts/build_native_release.py --clean

      - name: Upload artifacts
        uses: actions/upload-artifact@v4
        with:
          name: native-macos-arm64
          path: dist/native/*
          retention-days: 5

  build-windows:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set version
        id: version
        shell: bash
        run: echo "version=$(cat VERSION | tr -d '[:space:]')" >> "$GITHUB_OUTPUT"

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: "npm"
          cache-dependency-path: apps/frontend/package-lock.json

      - name: Build frontend
        run: cd apps/frontend && npm ci && npm run build

      - name: Build native binary
        shell: bash
        run: |
          python -m pip install --upgrade pip
          pip install -r apps/backend/requirements.txt
          pip install -r apps/backend/requirements-pg.txt
          pip install pyinstaller
          python scripts/build_native_release.py --clean

      - name: Upload artifacts
        uses: actions/upload-artifact@v4
        with:
          name: native-windows-amd64
          path: dist/native/*
          retention-days: 5

  publish:
    needs: [build-linux, build-macos, build-windows]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/download-artifact@v4
        with:
          path: artifacts/
          merge-multiple: false

      - name: Collect all artifacts
        run: |
          mkdir -p release/
          find artifacts/ -type f \( -name "*.tar.gz" -o -name "*.zip" -o -name "*.deb" -o -name "*.rpm" -o -name "*.sha256" -o -name "*.json" \) \
            -exec cp {} release/ \;
          ls -la release/

      - name: Upload to GitHub Release
        if: startsWith(github.ref, 'refs/tags/v')
        uses: softprops/action-gh-release@v2
        with:
          files: release/*
          fail_on_unmatched_files: false
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/native.yml
git commit -m "feat: add native.yml CI workflow for cross-platform binary builds

Builds PyInstaller binaries + deb/rpm packages on Linux (amd64/arm64),
macOS (arm64), and Windows (amd64). Uploads all artifacts to the GitHub
Release on v* tags."
```

---

### Task 10: Update release.yml to Remove Duplicate and Link to native.yml

The existing `release.yml` creates a bare GitHub Release. Now that `native.yml` uploads artifacts to the same release, we need to ensure they don't conflict.

**Files:**
- Modify: `.github/workflows/release.yml`

- [ ] **Step 1: Verify release.yml uses softprops/action-gh-release@v2**

Both workflows use `softprops/action-gh-release` which is additive (won't overwrite). The `release.yml` creates the release with auto-generated notes, and `native.yml` adds binary artifacts to it. This should work as-is since both trigger on `v*` tags.

No code change needed — just verify they're compatible. If release.yml runs first and creates the release, native.yml's publish job will add files to the existing release.

- [ ] **Step 2: Commit (if changes needed)**

Only commit if modifications were required.

---

## Chunk 4: macOS Support

### Task 11: Create macOS launchd Plist

**Files:**
- Create: `packaging/com.blkleg.circuitbreaker.plist`

- [ ] **Step 1: Write the launchd plist**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.blkleg.circuitbreaker</string>

  <key>ProgramArguments</key>
  <array>
    <string>__CB_BINARY_PATH__</string>
    <string>serve</string>
    <string>--config</string>
    <string>__CB_CONFIG_PATH__</string>
  </array>

  <key>RunAtLoad</key>
  <true/>

  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key>
    <false/>
  </dict>

  <key>StandardOutPath</key>
  <string>__CB_LOG_DIR__/circuit-breaker.log</string>
  <key>StandardErrorPath</key>
  <string>__CB_LOG_DIR__/circuit-breaker.err</string>

  <key>WorkingDirectory</key>
  <string>__CB_DATA_DIR__</string>

  <key>EnvironmentVariables</key>
  <dict>
    <key>CB_DATA_DIR</key>
    <string>__CB_DATA_DIR__</string>
  </dict>
</dict>
</plist>
```

The `__CB_*__` placeholders are replaced by the installer with actual paths.

- [ ] **Step 2: Commit**

```bash
git add packaging/com.blkleg.circuitbreaker.plist
git commit -m "feat: add macOS launchd plist template for native installs

Template with placeholder paths replaced by installer. Keeps the service
alive on failure and logs to ~/Library/Logs/CircuitBreaker/."
```

---

### Task 12: Add macOS Support to install.sh

**Files:**
- Modify: `install.sh` — Add macOS detection in `Check_OS()`, macOS paths in `Install_Binary_Mode()`, launchd setup function

- [ ] **Step 1: Add macOS path defaults**

Near the top of install.sh (after existing CB_BINARY_* defaults around line 43-47), add:
```bash
# ─── macOS defaults ────────────────────────────────────────────────────────
CB_MACOS_APP_SUPPORT="${HOME}/Library/Application Support/CircuitBreaker"
CB_MACOS_LOG_DIR="${HOME}/Library/Logs/CircuitBreaker"
CB_MACOS_CONFIG_DIR="${HOME}/.config/circuitbreaker"
CB_MACOS_PLIST_NAME="com.blkleg.circuitbreaker"
```

- [ ] **Step 2: Add Setup_Launchd_MacOS() function**

Add after the existing `Setup_Systemd_Binary()` function:
```bash
Setup_Launchd_MacOS() {
  local plist_dir="$HOME/Library/LaunchAgents"
  local plist_file="${plist_dir}/${CB_MACOS_PLIST_NAME}.plist"
  local binary_path="${CB_INSTALL_DIR}/circuit-breaker"
  local config_path="${CB_MACOS_CONFIG_DIR}/config.toml"
  local data_dir="${CB_MACOS_APP_SUPPORT}"
  local log_dir="${CB_MACOS_LOG_DIR}"

  mkdir -p "$plist_dir" "$data_dir" "$log_dir" "$CB_MACOS_CONFIG_DIR"

  # Copy plist template and replace placeholders
  local plist_src="${CB_INSTALL_DIR}/share/com.blkleg.circuitbreaker.plist"
  if [[ ! -f "$plist_src" ]]; then
    Show 3 "launchd plist template not found — skipping service setup."
    return
  fi

  sed -e "s|__CB_BINARY_PATH__|${binary_path}|g" \
      -e "s|__CB_CONFIG_PATH__|${config_path}|g" \
      -e "s|__CB_DATA_DIR__|${data_dir}|g" \
      -e "s|__CB_LOG_DIR__|${log_dir}|g" \
      "$plist_src" > "$plist_file"

  # Load the agent
  launchctl unload "$plist_file" 2>/dev/null || true
  launchctl load -w "$plist_file"
  Show 0 "launchd agent installed and loaded: $CB_MACOS_PLIST_NAME"
}
```

- [ ] **Step 3: Update Install_Binary_Mode() to branch on OS**

In `Install_Binary_Mode()`, after the current Linux-specific setup, add:
```bash
  # Platform-specific service setup
  case "$(uname -s)" in
    Linux)
      Setup_Systemd_Binary
      ;;
    Darwin)
      Setup_Launchd_MacOS
      ;;
    *)
      Show 3 "No service manager support for $(uname -s) — start manually."
      ;;
  esac
```

Replace the existing direct `Setup_Systemd_Binary` call with this case block.

- [ ] **Step 4: Update Create_User_And_Dirs() to handle macOS paths**

Add a macOS branch:
```bash
  if [[ "$(uname -s)" == "Darwin" ]]; then
    # macOS: use user-level directories (no system user needed)
    mkdir -p "$CB_MACOS_APP_SUPPORT" "$CB_MACOS_LOG_DIR" "$CB_MACOS_CONFIG_DIR"
    Show 0 "Created macOS directories."
    return
  fi
```

- [ ] **Step 5: Commit**

```bash
git add install.sh packaging/com.blkleg.circuitbreaker.plist
git commit -m "feat: add macOS native install support with launchd

Detect macOS in Install_Binary_Mode, use ~/Library paths, install launchd
agent instead of systemd. Plist template with placeholder substitution."
```

---

## Chunk 5: Auto-Update Check

### Task 13: Add Update Check Module

A lightweight startup check that queries GitHub Releases API and prints a notice if a newer version is available. No auto-install — just notification.

**Files:**
- Create: `apps/backend/src/app/core/update_check.py`

- [ ] **Step 1: Write the update check module**

```python
"""Non-blocking update check against GitHub Releases API."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

logger = logging.getLogger("circuitbreaker.update_check")

GITHUB_RELEASES_URL = (
    "https://api.github.com/repos/BlkLeg/CircuitBreaker/releases/latest"
)
CHECK_TIMEOUT = 5  # seconds


def _parse_version(v: str) -> tuple[int, ...]:
    """Parse 'v1.2.3' or '1.2.3-beta' into a comparable tuple."""
    clean = v.lstrip("v").split("-")[0]
    try:
        return tuple(int(x) for x in clean.split("."))
    except (ValueError, AttributeError):
        return (0, 0, 0)


async def check_for_update(current_version: str) -> Optional[str]:
    """Return latest version string if newer than current, else None.

    Returns None on any error (network, parse, timeout) — never blocks startup.
    """
    try:
        import httpx  # Use httpx if available (already a FastAPI dep via uvicorn)
    except ImportError:
        return None

    try:
        async with httpx.AsyncClient(timeout=CHECK_TIMEOUT) as client:
            resp = await client.get(
                GITHUB_RELEASES_URL,
                headers={"Accept": "application/vnd.github+json"},
                follow_redirects=True,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            latest = data.get("tag_name", "")
            if _parse_version(latest) > _parse_version(current_version):
                return latest
    except Exception:
        # Never let update check break the app
        return None
    return None


async def log_update_notice(current_version: str) -> None:
    """Log a notice if a newer version is available."""
    latest = await check_for_update(current_version)
    if latest:
        logger.info(
            "A newer version of Circuit Breaker is available: %s (current: %s). "
            "See https://github.com/BlkLeg/CircuitBreaker/releases/%s",
            latest,
            current_version,
            latest,
        )
```

- [ ] **Step 2: Wire into startup lifespan**

In `apps/backend/src/app/main.py`, in the lifespan function, add after all services are initialized (just before the `yield`):

```python
    # ── Phase 9: Update check (non-blocking) ──
    from app.core.update_check import log_update_notice
    asyncio.create_task(log_update_notice(settings.app_version))
```

This runs as a fire-and-forget task — it won't delay startup.

- [ ] **Step 3: Commit**

```bash
git add apps/backend/src/app/core/update_check.py apps/backend/src/app/main.py
git commit -m "feat: add non-blocking update check on startup

Queries GitHub Releases API (5s timeout) and logs a notice if a newer
version is available. Fire-and-forget — never blocks or crashes startup."
```

---

## Chunk 6: config.toml Loader

### Task 14: Add TOML Config Loader

Load `config.toml` on startup and set environment variables for any configured values. Env vars always take precedence (existing behavior preserved).

**Files:**
- Create: `apps/backend/src/app/core/config_toml.py`
- Modify: `apps/backend/src/app/start.py`

- [ ] **Step 1: Write the TOML config loader**

```python
"""Load config.toml and set env vars (env vars take precedence)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Python 3.11+ has tomllib in stdlib
if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib  # type: ignore[import]
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[import,no-redef]
        except ImportError:
            tomllib = None  # type: ignore[assignment]

# Map config.toml keys → environment variable names
_KEY_MAP: dict[str, str] = {
    "server.host": "CB_HOST",
    "server.port": "CB_PORT",
    "database.url": "CB_DB_URL",
    "database.pool_size": "DB_POOL_SIZE",
    "database.max_overflow": "DB_MAX_OVERFLOW",
    "redis.url": "CB_REDIS_URL",
    "nats.url": "CB_NATS_URL",
    "nats.auth_token": "NATS_AUTH_TOKEN",
    "security.vault_key": "CB_VAULT_KEY",
    "security.cors_origins": "CORS_ORIGINS",
    "discovery.docker_host": "CB_DOCKER_HOST",
    "discovery.proxmox_url": "CB_PROXMOX_URL",
    "paths.data_dir": "CB_DATA_DIR",
    "paths.log_dir": "CB_LOG_DIR",
    "paths.static_dir": "STATIC_DIR",
    "paths.alembic_ini": "CB_ALEMBIC_INI",
    "updates.check_on_startup": "CB_UPDATE_CHECK",
}


def _flatten(data: dict, prefix: str = "") -> dict[str, str]:
    """Flatten nested dict to dotted keys with string values."""
    result: dict[str, str] = {}
    for key, value in data.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            result.update(_flatten(value, full_key))
        else:
            result[full_key] = str(value)
    return result


def load_config_toml(config_path: str | Path | None = None) -> int:
    """Load config.toml and set env vars for unset keys.

    Returns the number of env vars set from the config file.
    """
    if tomllib is None:
        return 0

    if config_path is None:
        # Search standard locations
        candidates = [
            Path(os.environ.get("CB_CONFIG", "")),
            Path("/etc/circuit-breaker/config.toml"),
            Path.home() / ".config" / "circuitbreaker" / "config.toml",
            Path.cwd() / "config.toml",
        ]
        for candidate in candidates:
            if candidate.is_file():
                config_path = candidate
                break
        else:
            return 0
    else:
        config_path = Path(config_path)
        if not config_path.is_file():
            return 0

    with open(config_path, "rb") as f:
        data = tomllib.load(f)

    flat = _flatten(data)
    count = 0
    for toml_key, env_var in _KEY_MAP.items():
        if toml_key in flat and env_var not in os.environ:
            value = flat[toml_key]
            if value and value.lower() not in ("", "none", "null"):
                os.environ[env_var] = value
                count += 1

    return count
```

- [ ] **Step 2: Wire into start.py**

In `apps/backend/src/app/start.py`, in the `main()` function, add BEFORE the existing env loading:

```python
    # Load config.toml (env vars take precedence)
    from app.core.config_toml import load_config_toml
    config_count = load_config_toml(args.config if hasattr(args, 'config') else None)
    if config_count:
        print(f"[start] Loaded {config_count} setting(s) from config.toml")
```

- [ ] **Step 3: Add --config flag to argparse in start.py**

In the existing argparse setup, add:
```python
    parser.add_argument(
        "--config", "-c",
        default=None,
        help="Path to config.toml (default: auto-detect from standard locations)",
    )
```

- [ ] **Step 4: Commit**

```bash
git add apps/backend/src/app/core/config_toml.py apps/backend/src/app/start.py
git commit -m "feat: add config.toml support for native installs

Loads config.toml from /etc/circuit-breaker/, ~/.config/circuitbreaker/,
or --config flag. Maps TOML keys to env vars. Env vars always take
precedence. Uses stdlib tomllib (Python 3.11+)."
```

---

## Chunk 7: Update Uninstaller

### Task 15: Update uninstall.sh for All Modes

**Files:**
- Modify: `uninstall.sh`

- [ ] **Step 1: Add native binary cleanup**

After the existing Docker cleanup section, add:
```bash
# ─── Native binary cleanup ──────────────────────────────────────────────────
if [ -f /usr/local/bin/circuit-breaker ] || [ -f /etc/systemd/system/circuit-breaker.service ]; then
  echo ""
  echo -e "${aCOLOUR[0]}─────────────────────────────────────────────────────${COLOUR_RESET}"
  echo -e " ${aCOLOUR[1]}Native Binary Cleanup${COLOUR_RESET}"
  echo -e "${aCOLOUR[0]}─────────────────────────────────────────────────────${COLOUR_RESET}"
  echo ""

  # Stop systemd service
  if systemctl is-active --quiet circuit-breaker.service 2>/dev/null; then
    Show 2 "Stopping circuit-breaker service..."
    sudo systemctl stop circuit-breaker.service
    sudo systemctl disable circuit-breaker.service
    Show 0 "Service stopped and disabled."
  fi

  # Remove systemd unit
  if [ -f /etc/systemd/system/circuit-breaker.service ]; then
    sudo rm -f /etc/systemd/system/circuit-breaker.service
    sudo systemctl daemon-reload
    Show 0 "systemd unit removed."
  fi

  # Remove binary
  if [ -f /usr/local/bin/circuit-breaker ]; then
    sudo rm -f /usr/local/bin/circuit-breaker
    Show 0 "Binary removed."
  fi

  # Remove share directory
  if [ -d /usr/local/share/circuit-breaker ]; then
    sudo rm -rf /usr/local/share/circuit-breaker
    Show 0 "Share directory removed."
  fi

  # Config and data (ask first)
  echo ""
  printf "  Remove config (/etc/circuit-breaker)? [y/N] "
  read -r REPLY < /dev/tty
  case "$REPLY" in
    [yY]*) sudo rm -rf /etc/circuit-breaker; Show 0 "Config removed." ;;
    *) Show 2 "Config retained at /etc/circuit-breaker" ;;
  esac

  printf "  Remove data (/var/lib/circuit-breaker)? [y/N] "
  read -r REPLY < /dev/tty
  case "$REPLY" in
    [yY]*) sudo rm -rf /var/lib/circuit-breaker; Show 0 "Data removed." ;;
    *) Show 2 "Data retained at /var/lib/circuit-breaker" ;;
  esac
fi

# ─── macOS cleanup ──────────────────────────────────────────────────────────
if [ "$(uname -s)" = "Darwin" ]; then
  PLIST="$HOME/Library/LaunchAgents/com.blkleg.circuitbreaker.plist"
  if [ -f "$PLIST" ]; then
    echo ""
    echo -e "${aCOLOUR[0]}─────────────────────────────────────────────────────${COLOUR_RESET}"
    echo -e " ${aCOLOUR[1]}macOS Cleanup${COLOUR_RESET}"
    echo -e "${aCOLOUR[0]}─────────────────────────────────────────────────────${COLOUR_RESET}"
    echo ""

    launchctl unload "$PLIST" 2>/dev/null
    rm -f "$PLIST"
    Show 0 "launchd agent removed."

    if [ -d "$HOME/Library/Application Support/CircuitBreaker" ]; then
      printf "  Remove app data? [y/N] "
      read -r REPLY < /dev/tty
      case "$REPLY" in
        [yY]*) rm -rf "$HOME/Library/Application Support/CircuitBreaker"; Show 0 "App data removed." ;;
        *) Show 2 "App data retained." ;;
      esac
    fi
  fi
fi
```

- [ ] **Step 2: Commit**

```bash
git add uninstall.sh
git commit -m "feat: extend uninstaller for native binary and macOS modes

Cleans up binary, systemd unit, share directory, config, and data for
native installs. Handles macOS launchd agent and Library paths. Always
prompts before deleting user data."
```

---

## Summary: Execution Order & Dependencies

```
Chunk 1 (Fix Broken Paths)     ← Do first, unblocks current users
  Task 1: Fix compose mode
  Task 2: Add native dependency guidance

Chunk 2 (Linux Packaging)      ← Core deliverable
  Task 3: Canonical systemd unit
  Task 4: Post-install/pre-remove scripts
  Task 5: nfpm.yaml
  Task 6: Default config.toml
  Task 7: build_native_release.py + nfpm
  Task 8: Makefile targets

Chunk 3 (CI Pipeline)          ← Requires Chunk 2
  Task 9: native.yml workflow
  Task 10: release.yml compatibility

Chunk 4 (macOS)                ← Independent of Chunks 2-3
  Task 11: launchd plist
  Task 12: install.sh macOS support

Chunk 5 (Auto-Update)          ← Independent
  Task 13: Update check module

Chunk 6 (config.toml)          ← Independent
  Task 14: TOML config loader

Chunk 7 (Uninstaller)          ← After Chunks 1, 2, 4
  Task 15: Extend uninstall.sh
```

## Out of Scope (Future Work)

| Item | Reason |
|------|--------|
| **Rust/Tauri rewrite** | Massive effort; PyInstaller delivers the same UX today |
| **Windows MSI/EXE installer** | Low priority for homelab audience; .zip + docs sufficient for now |
| **Windows Service (NSSM)** | Deferred until Windows user demand exists |
| **AppImage** | Nice-to-have; .deb/.rpm/.tar.gz cover 99% of Linux users |
| **Homebrew tap** | Can add after native.yml is working (just a formula pointing to the .tar.gz) |
| **macOS code signing / notarization** | Requires Apple Developer account; add when ready for public distribution |
| **Auto-install updates** | Security risk; notification-only is the right default |

## Exit Criteria (from PROD_IMAGE.md)

After all chunks are complete:

```
Linux:
  dpkg -i circuit-breaker_0.2.2_amd64.deb
  sudo systemctl start circuit-breaker
  curl http://localhost:8080/api/v1/health  →  {"status":"ok"}

  systemctl stop circuit-breaker → clean shutdown
  apt remove circuit-breaker → service stopped, binary removed, data preserved

macOS:
  tar xzf circuit-breaker_0.2.2_macos_arm64.tar.gz
  ./install.sh --mode binary
  curl http://localhost:8080/api/v1/health  →  {"status":"ok"}
  launchctl list | grep circuitbreaker  →  running

Docker (all platforms):
  curl -fsSL https://raw.githubusercontent.com/.../install.sh | bash
  → Interactive prompt → Docker/Compose/Native → working in < 2 minutes

All:
  Auto-update check on startup (log notice only)
  config.toml for native installs
  Graceful shutdown (SIGTERM)
  Multi-arch (amd64/arm64)
```
