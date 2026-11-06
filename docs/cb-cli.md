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

## Terminal presentation

Help groups commands by operator task. Status separates application units from
shared nginx and shows process state and active-since timestamps; `cb doctor`
checks readiness. Doctor displays passed, failed, warning and skipped counts,
including skipped authenticated checks, without changing its JSON verdict.

Resources uses the approved CLI palette, keeps shared usage outside application
totals, and wraps narrow output. Interactive logs align recognized entries;
redirected logs retain their original stream. Backup shows measured phase times,
actual size and permissions, online consistency and whether the archive was
verified. Verification is separate from a restore rehearsal.

The npm lifecycle renderer supports `--no-animation`, `CB_REDUCED_MOTION=1`,
`NO_COLOR`, ASCII fallback and narrow/short terminals. Its download bar measures
bytes only; completion follows the authoritative native result. Purge confirmation
requires the exact phrase `DELETE circuitbreaker` or explicit `--yes`.

## Command availability by install mode

| Command | Native | Mono (Docker/Compose) | Package (advanced) |
|---|---|---|---|
| `info`, `status`, `resources`, `doctor`, `diag bundle`, `setup`, `setup-token`, `logs`, `restart`, `backup`, `restore`, `config validate`, `version`, `uninstall` | ✅ | ✅ | ✅ |
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

### `cb diag bundle`

```bash
cb diag bundle [--output <path>]
```

Collects `install.log`, `cb doctor --json`, the `circuit-breaker --selftest`
output, unit status, journal output, the install identity, and the redacted
env file into one `.tar.gz` — one file to attach to an issue instead of
copy-pasting several. Every file it collects has, at some point, held a JWT
secret, a Fernet vault key, or a database password, so every source is passed
through the same redaction that already masks secrets and connection-string
credentials, with no truncation — a 500-line log stays a 500-line log, fully
redacted, not a 500-character fragment.

It fails closed: without `python3` on `PATH` it refuses to produce a bundle at
all and exits non-zero, rather than ship anything unredacted. It never uploads
anything — it writes the archive and prints its path; where that file goes
from there is up to you.

---

## Common commands

### `cb status`

Show container or systemd unit status for the active mode.

### `cb resources`

Measure Circuit Breaker's local resource footprint, including its API, workers,
and dedicated dependencies. Works without a running backend or database and does
not read the app's secrets, change resource limits, or enable accounting.

```bash
cb resources                         # snapshot over 2 seconds
cb resources --watch                 # live view; q or Ctrl-C exits
cb resources --watch --interval 5     # refresh/sample interval, minimum 1 second
cb resources --json                   # one JSON document
cb resources --watch --json           # JSON Lines for scripts
```

Native/Proxmox and package installs use verified systemd service cgroups. Native
PostgreSQL and `cb-helperd` are included even though they sit outside the app slice.
The system nginx service is shown separately as shared usage. Docker/Compose uses
the exact container in install identity and honors the selected Docker context;
capacity figures come from that daemon's host/VM, including for remote contexts.
Inside the mono container, visible cgroup v2 counters can be read without a Docker
socket; use the host command if the container's accounting boundary is hidden.

CPU is measured in cores consumed (`1.00` = one busy logical CPU). Memory is charged
memory **including cache**, with cache and swap also shown separately; this differs
from Docker CLI's cache-subtracted display. I/O values are rates over the actual
sample interval. JSON preserves cumulative counters, per-metric sources and missing
value reasons, scope-specific limits, and coverage notices (`schema_version: 1`).
Missing counters are `null`, and incomplete totals are labeled observed subtotals.

Live terminal controls: `c` sorts by CPU, `m` by memory, `e` expands workers, and
`j`/`k` scroll through component details, limits, and coverage notices.
Redirected output has timestamped snapshots without terminal control codes.
Collection rechecks membership and resets rate baselines after restarts or counter
resets. Limits apply to their named service/slice/container, not necessarily the
whole application; visible host/guest capacity may exceed an enclosing quota.

Coverage depends on the installation:

- Native network rates require existing systemd IP accounting. Host networking or
  shared Docker network namespaces cannot supply app-only network rates.
- Native totals sum verified service cgroups; residual charges directly on parent
  slices are not assigned to the app. The optional Docker proxy includes its
  launcher and verified container on the local system daemon; an unreadable local
  Docker socket produces an explicit gap and partial totals.
- Shared host services, external databases, remote agents, browser usage, and jobs
  launched outside managed app services are outside app totals. Package installs
  include the dedicated `circuit-breaker-nats` service when present, but cannot
  attribute a shared system database to this app.
- Mono currently reports container totals. Internal process breakdowns and the
  optional disk footprint scan are follow-up features, not current flags.

Requires Python 3.9+ (the bundled interpreter is preferred). The host Docker path
also requires the Docker CLI and access to its daemon; native needs access to
systemd and readable accounting counters. An unreadable identity needs an account
with permission to read it, rather than a reinstall. A missing/invalid identity
must be repaired; resource accounting does not guess from legacy `install.conf`.

Exit status: `0` for a usable report, including explicitly partial reports; `1`
when installation scope/runtime cannot be collected; `2` for invalid arguments.

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

`cb restore` takes a snapshot tarball (`cb-snapshot-*.tar.gz[.age]`) only. A bare
`pre-upgrade-*.sql` (or `.sql.gz`) from `install.sh --upgrade` is a different
shape — database only, the upgrade rollback artifact — and is restored with
`deploy/scripts/restore.sh` directly, not through `cb restore`.

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
