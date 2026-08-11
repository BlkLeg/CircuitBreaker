# Circuit Breaker — Packaging & Installation

This directory documents the native and container packaging surface for Circuit Breaker.

## Packaging layout

```
packaging/
├── systemd/
│   ├── circuit-breaker-native.service
│   └── circuit-breaker.service
└── README.md
```

Native release archives are produced by `scripts/build_native_release.py` and contain:

```text
circuit-breaker(.exe)
share/
  VERSION
  DocsPage.md
  frontend/
  backend/alembic.ini
  backend/migrations/
manifest.json
```

## Release asset naming

All native archives follow the same pattern:

```text
circuit-breaker_<version>_<os>_<arch>.<ext>
```

Examples:

- `circuit-breaker_v0.2.0_linux_amd64.tar.gz`
- `circuit-breaker_v0.2.0_linux_arm64.tar.gz`
- `circuit-breaker_v0.2.0_macos_arm64.tar.gz`
- `circuit-breaker_v0.2.0_windows_amd64.zip`

Each archive is published with a sidecar checksum file and a JSON manifest.

## PostgreSQL major version and TimescaleDB (mono / container)

The mono image (`Dockerfile.mono`) targets **PostgreSQL 15** with the Debian package
`timescaledb-2-postgresql-15`. Bumping the embedded Postgres major version requires a
matching TimescaleDB build string and an image rebuild; do not change only the server
version without updating the Timescale package line in the Dockerfile.

## Building native packages

| Target | Use case |
|--------|----------|
| `make build-native` | Fast local build using your system Python. Output may not run on older Linux (e.g. glibc &lt; 2.42). |
| `make build-native-docker` | Build inside Ubuntu 22.04 (glibc 2.35). Use this when the binary must run on older VMs (Debian 11, Ubuntu 20.04, etc.). |

If you see `GLIBC_ABI_GNU2_TLS not found` when running the binary on a VM, rebuild with `make build-native-docker` and rsync the new package.

## Packaging platform inventory

This table describes packaging output and installer coverage. It is not, by itself, the 1.0.0
support matrix. The release support boundary lives in
[`docs/release/1.0.0-support-contract.md`](../docs/release/1.0.0-support-contract.md).

| Platform        | Native package           | Installer story              | 1.0.0 support status               | Notes                                                     |
| --------------- | ------------------------ | ---------------------------- | ---------------------------------- | --------------------------------------------------------- |
| Linux `amd64`   | Yes                      | `install.sh --mode binary`   | Supported candidate                | Primary native target after ACC evidence passes           |
| Linux `arm64`   | Yes                      | `install.sh --mode binary`   | Supported candidate                | ARM64 acceptance must include agent and AVIF checks       |
| Linux `arm/v7`  | No                       | Docker only                  | Unsupported for 1.0.0              | Native packaging intentionally not shipped                |
| macOS `arm64`   | Build-script target only | Manual archive install today | Unsupported for 1.0.0 server/agent | Native archive is not a supported installer/service story |
| Windows `amd64` | Build-script target only | Manual archive install today | Unsupported for 1.0.0 server/agent | Native `.exe` is not a supported installer/service story  |

## Linux native runtime contract

Linux native installs use:

- Binary: `/usr/local/bin/circuit-breaker`
- Share dir: `/usr/local/share/circuit-breaker`
- Config: `/etc/circuit-breaker/config.yaml`
- Env file: `/etc/circuit-breaker/env`
- Data dir: `/var/lib/circuit-breaker`
- Logs dir: `/var/log/circuit-breaker`

The native binary now supports:

```bash
circuit-breaker --config /etc/circuit-breaker/config.yaml
circuit-breaker --version
```

The generated config file is YAML-like and drives host/port, data paths, worker count, and optional TLS cert/key paths. The env file carries install-derived values such as `CB_SHARE_DIR`, `CB_ALEMBIC_INI`, `CB_DOCS_SEED_FILE`, and `APP_VERSION`.

## Native HTTPS modes

Linux native installs support two HTTPS paths:

1. `local`
   The installer generates a local CA plus server certificate, stores them under `/etc/circuit-breaker/certs`, and can optionally trust the CA in the local system/browser trust stores.
2. `provided`
   The installer copies your existing certificate and key into the managed cert directory and wires the native service to use them directly.

`install.sh` remains Linux-only. macOS and Windows currently consume the native archives manually.

## One-line installer URLs

The canonical install scripts live at the repo root so their `curl | bash` URLs remain stable:

```bash
# Install
curl -fsSL https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/install.sh | bash

# Uninstall
curl -fsSL https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/uninstall.sh | bash
```
