# cb — Command-Line Tool

`cb` is the management CLI for Circuit Breaker. One implementation ships for every
supported install mode. It reads a versioned **install identity** record
(`install-identity.json`) written by the installer, then dispatches to
mode-aware status, diagnosis, backup, and lifecycle commands.

Machine-readable mode details live in
[`specs/install/compatibility-matrix.yaml`](../specs/install/compatibility-matrix.yaml).

---

## Installation

Every first-class installer installs the same CLI to `/usr/local/bin/cb`:

| Install method | How `cb` is installed |
|---|---|
| Native (`install.sh`) | Automatic — copies the canonical CLI during setup stage 9 |
| Mono / Docker Compose (`install.sh --docker`) | Automatic when run from a checkout that contains `cb`; otherwise `sudo install -Dm755 ./cb /usr/local/bin/cb` |
| Proxmox LXC | Same as native inside the CT |
| Distro packages (advanced) | Ships `/usr/local/bin/cb` via `nfpm.yaml` |

Running `cb` with no arguments (or `cb help`) prints the command list.

---

## Install identity

After install, run:

```bash
cb info
cb info --json
```

Identity search order (no guessing of container names or ports):

1. `$CB_IDENTITY_PATH` (if set, this path alone — fail closed when missing)
2. `/etc/circuitbreaker/install-identity.json` (native / Proxmox)
3. `/etc/circuit-breaker/install-identity.json` (packages)
4. `$CB_DATA_DIR/install-identity.json` (mono data volume)
5. `~/.circuit-breaker/install-identity.json` (Compose host)

A missing or malformed identity is a diagnosis failure. Legacy
`~/.circuit-breaker/install.conf` / `/etc/circuit-breaker/install.conf` remains a
one-release compatibility hint; `cb info` and `cb doctor` tell you to migrate by
re-running the installer.

Schema: [`specs/install/identity.schema.json`](../specs/install/identity.schema.json).

---

## Command availability by install mode

| Command | Native | Mono (Docker/Compose) | Package (advanced) |
|---|---|---|---|
| `info`, `status`, `doctor`, `setup`, `setup-token`, `logs`, `restart`, `backup`, `restore`, `config validate`, `version`, `uninstall` | ✅ | ✅ | ✅ |
| `migrate`, `token`, `user`, `agent` | ✅ | ✅ | ✅ |
| `update` | ✅ (via installer guidance) | ✅ | ✅ |
| `vault-recover` | ✅ | ✅ | ✅ |

`migrate`, `token`, `user` and `agent` are the headless administration commands
(SRV-06). They need a reachable database.

Unsupported operations fail with the detected mode, why the operation is
unavailable, and the supported alternative.

---

## Configuration

Prefer **install identity**. Paths, container names, compose files, and health
URLs come from that record.

On native/Proxmox installs the CLI also sources `/etc/circuitbreaker/.env` so
admin commands see the same environment as the units.

On package installs the env file is `/etc/circuit-breaker/circuit-breaker.env`
(also recorded in identity).

---

## First-run setup

```bash
cb setup          # pending vs complete (bootstrap status)
cb setup-token    # print the one-time token once (never paste into doctor/logs)
```

Backend bootstrap status (`needs_bootstrap`) is authoritative. The mono image
no longer writes `.oobe-complete` before account creation.

---

## Diagnosis

```bash
cb doctor
cb doctor --json
```

Human output is concise; `--json` emits an array matching
[`specs/install/diagnostic-result.schema.json`](../specs/install/diagnostic-result.schema.json).
Evidence is bounded and redacted (no vault keys, JWTs, or passwords).

To include application-layer checks from the authenticated admin API, set a bearer
token and re-run:

```bash
export CB_ADMIN_TOKEN="<admin API token>"
cb doctor --json
```

When `CB_ADMIN_TOKEN` is unset, doctor adds a `diagnostics/admin` row with status
`skipped` and does not call the API. Never put the token value in logs or support
bundles.

Authenticated detail is also available directly:

```http
GET /api/v1/admin/diagnostics
```

Public probes (`/livez`, `/startupz`, `/readyz`, `/health`) are unchanged —
liveness stays process-only; readiness stays dependency-aware.

### Troubleshooting tree (doctor component)

| `component` / result | What to do |
|---|---|
| `identity` fail | Re-run the installer for your mode; then `cb info` |
| `docker` / `container` fail | Start Docker / `cb restart` |
| `postgres` fail | Check DB process/credentials; fix top-down |
| `redis` warn | Optional for inventory; restore Redis for pub/sub |
| `backend` fail | Inspect logs: `cb logs` |
| `storage` warn | Free space under 1 GiB — prune backups or grow volume |
| `workers` fail/warn | Restart workers; check `*.healthy` under the data dir |

---

## Common commands

### `cb status`

Show container or systemd unit status for the active mode.

### `cb doctor [--json]`

Top-down health checks with remediation. Exit non-zero when any check fails.

### `cb logs [-f]`

Tail application logs (docker logs or journalctl).

### `cb restart`

Restart the mono container, compose stack, package unit, or native target.

### `cb update`

Pull/recreate for mono; native/package point at the installer or package manager.

### `cb backup` / `cb restore`

Full-state snapshot and restore. See [Backup & Restore](backup-restore.md).

### `cb uninstall`

Remove the installation for the detected mode.

---

## Air-gap / offline

With `CB_AIRGAP=true` the application does not make outbound calls. Install and
upgrade using local bundles or package files. `cb doctor` still works offline
against local services; image pulls and remote installer curls will fail as
expected — use artifacts already on the host.

---

## Related

- [Installation overview](installation/index.md)
- [First-run setup](installation/first-run.md)
- [Compatibility matrix](../specs/install/compatibility-matrix.yaml)
