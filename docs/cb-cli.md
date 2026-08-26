# cb — Command-Line Tool

`cb` is the management CLI for Circuit Breaker. It wraps the systemd units (native installs) or
the containers (Docker and Compose installs), the health checks, and the database backup so you do
not have to remember unit or container names.

Two scripts implement it — `deploy/cli/cb` on native systemd installs and the repo-root `cb` on
docker/compose/binary installs. They expose the **same commands**; only the mechanics underneath
differ, and the one command that is not shared is called out in the table below.

---

## Installation

The native installer copies `deploy/cli/cb` to `/usr/local/bin/cb` during its "Installing
Management CLI" stage (`deploy/setup.sh`, stage 9). That is the only automatic install.

**No installer ships the repo-root `cb`.** `install.sh --docker` deploys the compose stack and
stops there, and the packages install the `circuit-breaker` binary but not this CLI, so on
docker/compose/binary installs you install `cb` yourself from a checkout. See
[Known gaps](#known-gaps).

| Install method | How to get `cb` |
|---|---|
| One-line installer (`install.sh`), native path | `deploy/cli/cb` installed automatically at `/usr/local/bin/cb` |
| `install.sh --docker` / Docker Compose / deb-rpm-apk | Manual: `sudo install -Dm755 ./cb /usr/local/bin/cb` from a checkout |

If the native copy fails, the installer falls back to telling you to use `systemctl status
circuitbreaker.target` and `journalctl -u 'circuitbreaker-*'` directly.

Running `cb` with no arguments prints the command list.

---

## Command availability by install mode

| Command | Native | Docker | Compose | Binary |
|---|---|---|---|---|
| `status`, `doctor`, `logs`, `restart`, `update`, `backup`, `config validate`, `version`, `uninstall` | ✅ | ✅ | ✅ | ✅ |
| `migrate`, `token`, `user`, `agent` | ✅ | ✅ | ✅ | ✅ |
| `restore` | — | ✅ | ✅ | ✅ |
| `vault-recover` | — | ✅ | ✅ | ✅ |

`migrate`, `token`, `user` and `agent` are the headless administration commands (SRV-06): schema
state, scoped API tokens, local accounts and the agent fleet, without a browser session. Both
scripts route them to the backend's own administration CLI — `python -m app.cli <group>` inside the
backend container on `docker`/`compose`, and the packaged binary's `--admin` passthrough on `native`
and `binary`, after sourcing the environment file that holds the database credentials and the vault
key. They need the database, so the stack must be reachable; `config validate` is the only command
that is deliberately offline.

`vault-recover` writes a vault key into the deployment's env file for installs made by the
container/binary installer path. Native installs keep that key in `/etc/circuitbreaker/.env`,
which the systemd units and `deploy/setup.sh` own, so the native `cb` does not ship the command —
edit that file and restart `circuitbreaker.target` instead.

`restore` is likewise absent from the native `cb` (`deploy/cli/cb`). A native install restores with
`deploy/scripts/restore.sh`, which `cb restore` drives in `binary` mode and which stays directly
callable — see [Backup & Restore](backup-restore.md#full-restore-disaster-recovery).

Everything else behaves the same way from the outside; where the mechanics differ (which port is
probed, what a backup contains) it is noted in the command's own section below.

---

## Configuration

On native installs `cb` has no config file of its own. It sources `/etc/circuitbreaker/.env` — the
same environment file the services use — on every run, so it picks up `CB_DATA_DIR`,
`CB_DB_PASSWORD`, `CB_REDIS_PASSWORD`, `CB_PORT`, `CB_FQDN`, and `DOCKER_PROXY_ENABLED` from your
install.

On docker/compose/binary installs `cb` reads `~/.circuit-breaker/install.conf` (falling back to
`/etc/circuit-breaker/install.conf`). That file sets `CB_MODE`, `CB_CONTAINER`,
`CB_BACKEND_CONTAINER`, `CB_DATA_DIR`, `CB_PORT`, `CB_IMAGE`, `CB_BINARY_ENV_FILE`, and the compose
paths, and every command dispatches on `CB_MODE`.

**You write `install.conf` yourself — no installer writes it** (see
[Known gaps](#known-gaps)). Without it `cb` prints
`Install config not found at … — using defaults.` and assumes `CB_MODE=docker` with the container
named `circuit-breaker` on port 8080, which is wrong for a compose or binary install. A minimal
file for each mode:

```bash
# ~/.circuit-breaker/install.conf — compose
CB_MODE=compose
CB_BACKEND_CONTAINER=cb-backend
CB_INSTALL_DIR=$HOME/.circuitbreaker        # where install.sh --docker put the stack
CB_COMPOSE_FILE=$HOME/.circuitbreaker/docker-compose.yml
CB_PORT=8080
```

```bash
# ~/.circuit-breaker/install.conf — binary (deb/rpm/apk)
CB_MODE=binary
CB_PORT=8080
# Optional; defaults to the path packaging/postinstall.sh generates:
# CB_BINARY_ENV_FILE=/etc/circuit-breaker/circuit-breaker.env
```

`cb update` (docker mode) also reads an optional `~/.circuit-breaker/env` and passes it to
`docker run --env-file`. That file is operator-supplied too; nothing creates it, and the command
works without it.

---

## Commands

### `cb status`

Prints a table of every Circuit Breaker systemd unit with its active state and the time it entered
that state.

```
cb status
```

Units covered: `circuitbreaker-postgres`, `circuitbreaker-pgbouncer`, `circuitbreaker-redis`,
`circuitbreaker-nats`, `circuitbreaker-backend`, the workers
(`circuitbreaker-worker@discovery`, `@notification`, `@telemetry`, `@monitor_scheduler`,
`@monitor_poll`), and `nginx`. `circuitbreaker-docker-proxy` is added to the list when
`DOCKER_PROXY_ENABLED=true`.

On container installs it prints the container's image, start time and status instead (`docker`),
or the `cb-*` container table (`compose`); on `binary` it shells out to `systemctl status
circuit-breaker`.

---

### `cb doctor`

Runs a top-down health check of the whole stack, ordered so that the first failure is usually the
cause of every failure below it. On native installs, if you are not root it re-executes itself
under `sudo` automatically; on a host with no `sudo` it says so and runs the checks it can rather
than aborting.

```
cb doctor
```

Checks performed on a native install, in order:

| Check | What it proves |
|---|---|
| PostgreSQL (5432) | The database is listening |
| pgbouncer (6432) | The pooler is listening |
| DB connection | `psql` can authenticate through pgbouncer as `breaker` |
| Redis (6379) | Redis answers `PING` with the configured password |
| Redis data dir ownership | `${CB_DATA_DIR}/redis` is owned by the Redis service user, so `BGSAVE` can write |
| SELinux context on Redis data dir | The directory is labelled `redis_var_lib_t` (SELinux hosts only) |
| NATS (4222) | The internal bus is listening |
| Backend API (8000) | `/api/v1/health` answers directly |
| Docker proxy (2375) | Only when `DOCKER_PROXY_ENABLED=true` |
| nginx (443, or `CB_PORT` when TLS is off) | The web front end is listening |
| nginx → backend proxy | A request actually routes *through* nginx to the API — catches the SELinux `httpd_can_network_connect` case that leaves every other check green while the UI 502s |
| firewalld allows the port | The port is open off-box (only when firewalld is running) |
| SELinux allows nginx on the port | The port carries an SELinux port label (only when `semanage` is present) |

When a check fails, `cb doctor` prints a fix hint and then automatically runs a read-only
diagnostic — usually the tail of the relevant `journalctl` unit — so you do not have to go look it
up. It shows 30 lines by default; set `CB_DOCTOR_LINES` to change that:

```bash
CB_DOCTOR_LINES=100 sudo cb doctor
```

The installer does not gate on `cb doctor`. When an install stage fails it names `cb doctor`
as a re-check hint and runs it as one of the diagnostics it prints at that point; on a clean
install it is never invoked. Running it afterwards is the operator's job — and because it
exits non-zero when any check fails, a wrapper script can act on the result.

On `docker` and `compose` installs the same idea is applied to the containers:

| Check | What it proves |
|---|---|
| Docker daemon | Docker is installed and the daemon answers — nothing below can be checked without it |
| Container `<name>` | The backend container is in `docker ps` |
| Container not restarting | It is not crash-looping (the reason is tailed from `docker logs`) |
| Backend API | `/api/v1/health` answers *inside* the container (8080 for the mono image, 8000 for the compose backend) |
| Database | `psql` connects with the credentials the app itself uses (`CB_DB_URL`, else `CB_DB_PASSWORD`) |
| Free space on the data dir | At least 1 GiB free — Postgres, the WAL and uploads share that volume |
| Vault key persisted | A key is present in the environment or `${CB_DATA_DIR}/.env`, so restarts stay decryptable |
| Published port | `http://127.0.0.1:${CB_PORT}/api/v1/health` answers from the host — the only thing a user actually touches |

On `binary` installs it checks the `circuit-breaker` unit, the API on `CB_PORT`, free space on
`CB_DATA_DIR`, and `CB_DB_URL` (when `psql` is installed). `CB_DOCTOR_LINES` works the same way in
both scripts, and `cb doctor` exits non-zero when any check fails.

---

### `cb logs`

Tails the logs of every Circuit Breaker unit live. It takes no flags and always follows — press
`Ctrl+C` to stop.

```
cb logs
```

Under the hood this is a single `journalctl -f` across the postgres, pgbouncer, redis, nats,
backend, `circuitbreaker-worker@*`, and nginx units.

On container installs it is `docker logs --tail 100` against the backend container and it does
*not* follow unless you ask: `cb logs -f`. On `binary` it is `journalctl -u circuit-breaker`.

---

### `cb restart`

Restarts the whole stack through the systemd target, waits a few seconds, then prints `cb status`.

```
cb restart
```

On container installs it restarts the container (or each `cb-*` container of the compose stack);
on `binary` it restarts the `circuit-breaker` unit through `sudo systemctl`.

---

### `cb update`

Re-runs the official installer in upgrade mode (`install.sh --upgrade`), fetched from the project
repository. Requires outbound internet access.

```
cb update
```

On `docker` it pulls `CB_IMAGE` and recreates the container; on `compose` it runs `docker compose
pull` and `up -d`. `binary` installs cannot self-update — re-run `install.sh`.

---

### `cb backup`

On a native install, runs `pg_dump` through pgbouncer on `127.0.0.1:6432` as the `breaker` user and
writes an uncompressed SQL dump:

```
cb backup
```

Output path: `${CB_DATA_DIR}/backups/cb-backup-<YYYYmmdd-HHMMSS>.sql`. This is a database dump
only — it does not capture uploads, the vault key, or config files.

On docker/compose/binary installs it writes the **full-state snapshot** — the same artifact
`POST /admin/db/snapshot` and the nightly scheduled job produce, because all three call the one
builder (`services/backup/snapshot.py`) through `python -m app.cli snapshot create`. It lands in
`${CB_BACKUP_DIR:-~/.circuit-breaker/backups}` as `cb-snapshot-<YYYYmmdd-HHMMSS>.tar.gz`
containing:

| Member | What it is |
|---|---|
| `db.sql.gz` | `pg_dump` of the whole database, gzip-compressed, with a recorded sha256 |
| `uploads/` | The uploads directory |
| `config/` | Native-install config files, when there are any |
| `vault.key` | The vault key **in plaintext** — without it the dump's encrypted columns are unreadable. Resolved through the same chain the server uses (`CB_VAULT_KEY` cross-checked against `app_settings.vault_key_hash`, then `$CB_DATA_DIR/.env`, then the database), never straight from the environment: `cb backup` runs the builder in a fresh `docker exec` process, whose environment can still hold the key the container was *created* with rather than the one the database is encrypted with |
| `manifest.json` | Format version, install mode, `cb` version, timestamp, database name, the uploads count, the `db.sql.gz` sha256 and the config files captured |

The archive is written mode `0600` because it contains secrets — treat the file itself as one.
Verify one with `python -m app.cli snapshot verify <archive>`; restore it with `cb restore`. See
[Backup & Restore](backup-restore.md).

An archive produced by `cb backup` **before** this change (`database.sql` + `manifest.txt`) is a
different, older format: it carried no vault key and no uploads, and nothing restores it.

---

### `cb restore`

Restores a full-state snapshot. **Destructive** — it replaces the database, the uploads, and the
vault key of the install it is run on.

```
cb restore <archive.tar.gz> [--yes] [--force] [--no-safety-snapshot]
```

| Flag | Effect |
|---|---|
| `--yes` | Skip the interactive `RESTORE` confirmation |
| `--force` | Proceed even though the snapshot is from a newer Circuit Breaker version |
| `--no-safety-snapshot` | Do not take a snapshot of the current state first |

The order is the safety property: **verify → confirm → safety snapshot → stop → restore → start →
verify**. The archive is checked by the backend's own verifier before anything is stopped, so an
unrestorable archive costs a failed command rather than an outage, and a fresh `cb backup` of the
current state is taken before anything is destroyed. Declining the confirmation changes nothing.

On `docker` and `compose` the archive is replayed inside the backend container (Postgres stays up —
it is what is being restored into). `supervisorctl` stops `backend-api` and every `worker-*` program
by its real name from `docker/supervisord.mono.conf`, and a stop that fails aborts the restore
instead of warning. On `binary` it drives `deploy/scripts/restore.sh`, the native implementation,
rather than growing a second one beside it — passing it the deb/rpm/apk layout's env file, systemd
unit and database roles, because that script's own defaults are the `install.sh` layout, which
`binary` mode is not. `CB_RESTORE_SCRIPT` in `install.conf` overrides where `cb` looks for that
script.

Full procedure, per-mode mechanics, and what each archive member replaces:
[Backup & Restore](backup-restore.md#full-restore-disaster-recovery).

---

### `cb migrate`

Database schema state, and applying it. Both are read from the same migration chain the server runs
at startup, so the CLI cannot develop a different opinion about what "up to date" means.

```
cb migrate status [--json]
cb migrate upgrade
```

`status` reports the database's revision against this build's. **It exits `3` when the database is
behind** — a distinct code from "cannot reach the database", so a deployment script can tell the two
apart without parsing prose. `--json` emits machine-readable output instead of a table.

`upgrade` applies pending migrations through the server's own upgrade path, which takes the
transaction-scoped advisory lock in `migrations/env.py`. That makes it safe to run while the stack
is coming up and racing the API's own auto-migrate phase — one of them takes the lock, the other
waits.

Downgrade is not offered, because it is not supported: restore a verified pre-upgrade backup
instead. See [Compatibility policy § Downgrade and rollback](release/1.0.0-compatibility-policy.md#downgrade-and-rollback).

---

### `cb token`

Scoped API tokens and service accounts, without a browser session.

```
cb token create --label LABEL (--expires-in-days N | --never-expires)
                [--scopes SCOPE ...] [--preset NAME] [--actor EMAIL] [--json]
cb token list [--json]
cb token rotate TOKEN_ID [--overlap-hours N] [--actor EMAIL] [--json]
cb token revoke TOKEN_ID [--actor EMAIL]
```

| Flag | Effect |
|---|---|
| `--label` | Required. What the token is for — it is the only thing `list` can show you later |
| `--scopes` | Explicit grants, e.g. `--scopes read:* write:telemetry`. The grantable set is in the [API reference](reference/api.md#roles-and-scopes) |
| `--preset` | A named scope set instead of `--scopes`: `read_only`, `telemetry_ingest`, `read_write`, `full_access` |
| `--expires-in-days` / `--never-expires` | **One is required.** A token with no expiry has to be asked for explicitly; there is no silent default |
| `--overlap-hours` | On `rotate`, keep the previous secret working for N hours so holders can be updated first. Never past the token's own expiry. Default `0` — immediate cutover |
| `--actor` | The administrator the change is recorded against. Optional when the install has exactly one active administrator; required otherwise |

**The secret is printed once, at creation or rotation, and never again.** `list` shows the label,
scopes, expiry and last use — never the secret, because only a salted HMAC of it is stored.

---

### `cb user`

Local accounts. The [role hierarchy](reference/api.md#roles-and-scopes) is `viewer < editor < admin`.

```
cb user list [--json]
cb user create --email EMAIL [--role admin|editor|viewer] [--display-name NAME]
               [--password-stdin] [--actor EMAIL] [--json]
cb user set-role EMAIL ROLE [--actor EMAIL]
cb user disable EMAIL [--actor EMAIL]
cb user enable EMAIL [--actor EMAIL]
```

`--role` defaults to `viewer` — the least privilege that is still an account.

**There is deliberately no `--password` flag.** `argv` is visible to every process on the host, so a
password either arrives on stdin (`--password-stdin`, first line) or is generated and printed once:

```bash
printf '%s' "$NEW_PASSWORD" | cb user create --email ops@example.com --role editor --password-stdin
```

`disable` deactivates the account **and revokes its sessions**, so it takes effect immediately rather
than at the next token expiry.

---

### `cb agent`

Fleet administration without the UI. The approval decision is the security boundary described in
[cb-agent § Enrollment](agent.md#enrollment) — approve a fingerprint you recognise, not one that
merely appeared.

```
cb agent list [--status pending|active|revoked|rejected] [--json]
cb agent approve AGENT_ID [--actor EMAIL]
cb agent revoke AGENT_ID [--reason TEXT] [--actor EMAIL]
```

`approve` applies the **default capability grants** — `host_telemetry`, `remote_probe` and
`local_discovery` with their shipped defaults. The per-capability opt-outs the approval modal offers
are a UI affordance; to approve with a narrower set, use the UI or adjust the capabilities afterwards
with `PUT /api/v1/agents/{agent_id}/capabilities`.

A revoked device key is refused at `/enroll` outright — there is no silent re-enrollment. See
[Runbook 3 — duplicate agent](agent.md#3-duplicate-agent) if you meant to re-enrol a host.

---

### `cb config validate`

Validates the configuration **before** it is used, rather than discovering an invalid combination
when the service refuses to boot. It runs the backend's own validator, so `cb` never develops a
second, drifting opinion about what a valid configuration is.

```
cb config validate
```

| Mode | What it runs |
|---|---|
| Native | `/opt/circuitbreaker/bin/circuit-breaker --config-validate`, after re-sourcing `/etc/circuitbreaker/.env` (and `/run/circuitbreaker/vault.env`) with `set -a` so the validator sees exactly the environment the unit starts with |
| Docker / Compose | `python -m app.cli config validate` inside the backend container |
| Binary | `/usr/local/bin/circuit-breaker --config-validate`, after sourcing `/etc/circuit-breaker/circuit-breaker.env` (the file `packaging/postinstall.sh` generates and the units name in `EnvironmentFile=`; override with `CB_BINARY_ENV_FILE`) |

Exit status is `0` when the configuration is valid, `1` when it is not, and `2` if you pass
anything other than `validate`. Secret *values* are never printed — only the name of the setting at
fault.

---

### `cb vault-recover`

Recovery tool for a vault stuck in "ephemeral" state — no key was ever persisted, so anything
encrypted before the next restart becomes unreadable. Under normal operation the OOBE wizard
generates this key for you; you should only need this after a crash, a headless deploy, or a
deleted `.env`.

```
cb vault-recover
```

It generates a key, writes `CB_VAULT_KEY` into the deployment's env file (inside the container for
`docker`/`compose`, `CB_BINARY_ENV_FILE` — by default `/etc/circuit-breaker/circuit-breaker.env` —
for `binary`), and restarts the service. If a key is
already present it asks for confirmation first — overwriting one breaks decryption of every secret
already stored.

Not available on native installs; see [Command availability by install
mode](#command-availability-by-install-mode).

---

### `cb version`

Prints the contents of `/opt/circuitbreaker/share/VERSION`, or `unknown` if that file is missing.

```
cb version
```

On container installs it reads `/app/VERSION` from the backend container and falls back to the
image reference; on `binary` it runs `circuit-breaker --version`.

---

### `cb uninstall`

Removes Circuit Breaker **and all of its data**. It prompts for confirmation first
(`Remove Circuit Breaker and ALL data? [y/N]`) and does nothing unless you answer `y`.

```
sudo cb uninstall
```

What it removes:

- Stops and disables every `circuitbreaker-*` unit, the `circuitbreaker.target`, and `nginx`
- Kills any remaining processes owned by the `breaker` user
- Deletes the systemd unit, timer, target, and slice files, then reloads systemd
- Deletes `/opt/circuitbreaker`, `/etc/circuitbreaker`, `/etc/nats`, and **`$CB_DATA_DIR`**
- Deletes `/etc/nginx/conf.d/circuitbreaker.conf`, `/usr/local/bin/nats-server`, and
  `/usr/local/bin/cb`
- Deletes the `breaker` system user and its home directory
- Removes the `/etc/hosts` entry for `CB_FQDN`
- Removes the **nginx package itself** and the NodeSource apt repository files
- Stops and removes the `cb-docker-proxy` container, if one exists

!!! warning "This deletes your data directory"
    `$CB_DATA_DIR` holds the database, uploads, and TLS certificates. Take a backup before running
    this if there is anything you want to keep.

On docker/compose/binary installs `cb uninstall` hands off to the repo's `uninstall.sh`. It looks
for, in order:

1. `/usr/local/bin/uninstall-circuit-breaker` — only present if **you** put it there; no installer
   creates it (see [Known gaps](#known-gaps));
2. `uninstall.sh` sitting next to the `cb` script — the checkout case;
3. otherwise it prints the two ways to run it and exits non-zero:

```bash
bash uninstall.sh                                                                    # from a checkout
curl -fsSL https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/uninstall.sh | bash
```

---

## The other two entry points

`cb` is a wrapper. Underneath it there are two more surfaces, and on some installs they are the only
ones available.

### The packaged binary

The deb/rpm/apk packages and the tarball install `circuit-breaker`, a frozen build of
`app/start.py`. A packaged host has no `python -m app.cli`, so the binary carries the flags itself:

| Flag | Effect |
|---|---|
| `--host HOST` | Override the listen host (default `127.0.0.1`, or `HOST`) |
| `--port PORT` | Override the listen port (default `8080`, or `PORT`) |
| `--workers N` | Uvicorn worker processes (default `1`, or `UVICORN_WORKERS`) |
| `--ssl-certfile PATH`, `--ssl-keyfile PATH` | Serve TLS from the backend itself. Both are required together, or startup exits |
| `--config PATH` | The native config file. A `.toml` path is also forwarded to the `config.toml` loader; anything else is read as the native YAML tier |
| `--worker-type TYPE` | Run as a background worker instead of the API server: `discovery`, `notification`, `telemetry`, `monitor_scheduler`, `monitor_poll`, `monitor_probe_dispatch` |
| `--version` | Print the resolved version and exit |
| `--config-validate` | Validate the configuration and exit non-zero if invalid. What `cb config validate` runs in native and binary mode |
| `--snapshot-create [--out DIR]` | Build a full-state snapshot and print its path. What `cb backup` runs in binary mode |
| `--snapshot-verify ARCHIVE` | Verify a snapshot archive. What `cb restore` runs before it stops anything |

The four `--config-validate` / `--snapshot-*` flags are handled **before argument parsing and before
anything binds a port, creates a directory or runs a migration** — so validating a broken
configuration cannot itself fail on the very dependency it is checking, and a one-shot snapshot does
not start a scheduler it has no use for.

### `python -m app.cli`

On a source checkout or inside the container, the same code is reachable as a module. This is what
`cb` executes in `docker` and `compose` mode.

| Group | Actions | Notes |
|---|---|---|
| `config` | `validate` | `--config PATH` picks the `config.toml`. Offline by construction — the pass replaces name resolution for its duration, so it cannot reach Postgres, Redis, NATS or a resolver |
| `snapshot` | `create`, `verify` | `create --out DIR` overrides `BACKUP_DIR`; `verify ARCHIVE` prints the manifest as JSON and exits non-zero if the archive cannot be restored |
| `migrate` | `status`, `upgrade` | Database schema state and forward migration |
| `token` | `create`, `list`, `rotate`, `revoke` | Scoped API tokens and service accounts |
| `user` | `list`, `create`, `set-role`, `disable`, `enable` | Local accounts |
| `agent` | `list`, `approve`, `revoke` | Fleet administration without a browser |

Each group has its own `cb` command documented above, except `snapshot`, which `cb backup` and
`cb restore` drive on your behalf.

!!! tip "The parser is the authority on flags"
    **Run `python -m app.cli <group> --help`** — or `<group> <action> --help` — for the exact flags
    of any of these. That output is generated from the parser and cannot go stale, which a table
    eventually can.

---

## Known gaps

Recorded here rather than papered over. None of these are wired up today:

| Gap | Effect | Workaround |
|---|---|---|
| No installer writes `install.conf` | `cb` on docker/compose/binary installs falls back to `CB_MODE=docker` defaults and prints a NOTICE | Write it by hand — see [Configuration](#configuration) |
| No installer delivers the repo-root `cb` | The docker/compose/binary CLI needs a git checkout | `sudo install -Dm755 ./cb /usr/local/bin/cb` |
| Nothing creates `/usr/local/bin/uninstall-circuit-breaker` | `cb uninstall` cannot use that path | Run `uninstall.sh` from a checkout, or let `cb uninstall` find it next to the script |

Closing the first two means teaching `install.sh` and the packages to emit `install.conf` and copy
`cb`; that is a change to the installers, not to the CLI, and has not been made.

---

## Related

- [Deployment & Security](deployment-security.md)
- [Backup & Restore](backup-restore.md)
- [API Reference](reference/api.md) — the surface that does go over HTTP
- [Configuration precedence and environment catalogue](reference/configuration-precedence.md) — what `cb config validate` checks
