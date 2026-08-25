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
| `vault-recover` | — | ✅ | ✅ | ✅ |

`vault-recover` writes a vault key into the deployment's env file for installs made by the
container/binary installer path. Native installs keep that key in `/etc/circuitbreaker/.env`,
which the systemd units and `deploy/setup.sh` own, so the native `cb` does not ship the command —
edit that file and restart `circuitbreaker.target` instead.

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
| `vault.key` | The vault key **in plaintext** — without it the dump's encrypted columns are unreadable |
| `manifest.json` | Format version, install mode, `cb` version, timestamp and the member checksums |

The archive is written mode `0600` because it contains secrets — treat the file itself as one.
Verify one with `python -m app.cli snapshot verify <archive>`; restore it with `cb restore`. See
[Backup & Restore](backup-restore.md).

An archive produced by `cb backup` **before** this change (`database.sql` + `manifest.txt`) is a
different, older format: it carried no vault key and no uploads, and nothing restores it.

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
