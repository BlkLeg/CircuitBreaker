# Circuit Breaker — Packaging & Installation

This directory documents the native and container packaging surface for Circuit Breaker.

## Packaging layout

```
packaging/
├── systemd/
│   ├── circuit-breaker-native.service
│   └── circuit-breaker.service
├── circuit-breaker.service              # shipped to /lib/systemd/system by nfpm.yaml
├── circuit-breaker.desktop
├── circuit-breaker-release-key.asc      # public key for verifying signed release artifacts
├── com.blkleg.circuitbreaker.plist      # launchd template, bundled by scripts/build_native_release.py
├── config.toml.default                  # seeded to /etc/circuit-breaker/config.toml by postinstall.sh
├── postinstall.sh                       # nfpm.yaml scripts.postinstall
├── preremove.sh                         # nfpm.yaml scripts.preremove
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
  config.toml.default
  com.blkleg.circuitbreaker.plist
agent-binaries/
deploy/
  config/ systemd/ nginx/ cli/ misc/ scripts/ helper/
  setup.sh
install.sh
manifest.json
```

The `deploy/` tree and `install.sh` are what make the `curl | bash` install work: `install.sh`
unpacks them into `/opt/circuitbreaker` and hands off to `deploy/setup.sh`.

## Release asset naming

All native archives follow the same pattern:

```text
circuit-breaker_<version>_<os>_<arch>.<ext>
```

Examples:

- `circuit-breaker_v1.0.0-rc.2_linux_amd64.tar.gz`
- `circuit-breaker_v1.0.0-rc.2_linux_arm64.tar.gz`
- `circuit-breaker_v1.0.0-rc.2_macos_arm64.tar.gz`
- `circuit-breaker_v1.0.0-rc.2_windows_amd64.zip`

Each archive is published with a sidecar checksum file and a JSON manifest.

## PostgreSQL major version and TimescaleDB (mono / container)

The mono image (`Dockerfile.mono`) targets **PostgreSQL 15** with the Debian package
`timescaledb-2-postgresql-15`. Bumping the embedded Postgres major version requires a
matching TimescaleDB build string and an image rebuild; do not change only the server
version without updating the Timescale package line in the Dockerfile.

## Building native packages

| Target | Use case |
|--------|----------|
| `make build` | Local build with the repo venv: frontend `npm run build`, then `scripts/build_native_release.py --clean`. Emits the tarball plus deb, rpm, apk, AppImage, and `.pkg.tar.zst`. |
| `make build-deps` | Install the build toolchain (nfpm, appimagetool, Python 3.12, Node 20) via `scripts/install-build-deps.sh`. |
| `make build-release` | `build-deps` then `build` — the full package set. |
| `make build-from-source` | Clean machine → artifacts: `build-deps`, `make install`, then `build`. |

`scripts/build_native_release.py` freezes the app with PyInstaller, so the resulting binary carries
the glibc requirement of the machine that built it. Build on the oldest distribution you intend to
support.

## Packaging platform inventory

This table describes packaging output and installer coverage. It is not, by itself, the 1.0.0
support matrix. The release support boundary lives in
[`docs/release/1.0.0-support-contract.md`](../docs/release/1.0.0-support-contract.md).

| Platform        | Native package           | Installer story                    | 1.0.0 support status               | Notes                                                     |
| --------------- | ------------------------ | ---------------------------------- | ---------------------------------- | --------------------------------------------------------- |
| Linux `amd64`   | Yes                      | `install.sh` (default native path) | Supported candidate                | Primary native target after ACC evidence passes           |
| Linux `arm64`   | Yes                      | `install.sh` (default native path) | Supported candidate                | ARM64 acceptance must include agent and AVIF checks       |
| Linux `arm/v7`  | No                       | Docker only                        | Unsupported for 1.0.0              | Native packaging intentionally not shipped                |
| macOS `arm64`   | Build-script target only | Manual archive install today       | Unsupported for 1.0.0 server/agent | Native archive is not a supported installer/service story |
| Windows `amd64` | Build-script target only | Manual archive install today       | Unsupported for 1.0.0 server/agent | Native `.exe` is not a supported installer/service story  |

## Linux native runtime contract

There are two distinct layouts. Which one you get depends on how the release was installed.

### Distro package (.deb / .rpm / .apk) layout

Paths shipped by `nfpm.yaml` and created by `packaging/postinstall.sh`:

- Binary: `/usr/local/bin/circuit-breaker`
- Share dir: `/usr/local/share/circuit-breaker`
- Config: `/etc/circuit-breaker/config.toml`
- Env file: `/etc/circuit-breaker/env`
- Data dir: `/var/lib/circuit-breaker`
- Logs dir: `/var/log/circuit-breaker`
- Unit: `circuit-breaker.service` (`/lib/systemd/system/circuit-breaker.service`)

The native binary supports:

```bash
circuit-breaker --config /etc/circuit-breaker/config.toml
circuit-breaker --version
```

The generated config file is TOML and drives host/port, data paths, worker count, and optional TLS cert/key paths. The env file carries install-derived values such as `CB_SHARE_DIR`, `CB_ALEMBIC_INI`, `CB_DOCS_SEED_FILE`, and `APP_VERSION`.

### `install.sh` native layout

The `curl | bash` installer uses unhyphenated paths instead:

- Binary: `/opt/circuitbreaker/bin/circuit-breaker`
- Share dir: `/opt/circuitbreaker/share`
- Deploy templates: `/opt/circuitbreaker/deploy`
- Agent binaries: `/opt/circuitbreaker/agent-binaries`
- Env file: `/etc/circuitbreaker/.env` (mode 0640, `root:breaker`)
- Data dir: `/var/lib/circuitbreaker`
- CLI: `/usr/local/bin/cb`

Its systemd units are `circuitbreaker-postgres`, `circuitbreaker-pgbouncer`, `circuitbreaker-redis`,
`circuitbreaker-nats`, `circuitbreaker-backend`, and `circuitbreaker-worker@*` — not the single
`circuit-breaker.service` the distro packages ship.

## Native HTTPS

There are no HTTPS "modes" to choose between. `install.sh` takes `--cert-type`, which accepts
`self-signed` (the default) or `letsencrypt` (`install.sh:591`). Either way the certificate and key
land in `${CB_DATA_DIR}/tls` — `/var/lib/circuitbreaker/tls` on a default install — as
`fullchain.pem` and `privkey.pem` (`deploy/setup.sh:757`, `:793-799`), and nginx is pointed at them.
Nothing is written to `/etc/circuit-breaker/certs`.

`install.sh` remains Linux-only. macOS and Windows currently consume the native archives manually.

## One-line installer URLs

The canonical install scripts live at the repo root so their `curl | bash` URLs remain stable:

```bash
# Install
curl -fsSL https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/install.sh | bash

# Uninstall — native and Proxmox LXC installs only
cb uninstall
```

The repo-root `uninstall.sh` is legacy: it targets the old Docker/Caddy layout (the
`circuit-breaker` container, the `circuit-breaker-data` volume, and `cb-caddy`) and does not know
about the `circuitbreaker-*` systemd units the current installer creates. Do not point native users
at it. See [Uninstalling](../docs/installation/uninstalling.md).
