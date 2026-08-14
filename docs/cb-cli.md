# cb — Command-Line Tool

`cb` is the management CLI for **native Linux installs** of Circuit Breaker. It wraps the systemd
units, health checks, and database backup so you do not have to remember unit names.

---

## Installation

`cb` is placed on the system by the native installer only. The install script copies
`deploy/cli/cb` to `/usr/local/bin/cb` during its "Installing Management CLI" stage.

| Install method | How to get `cb` |
|---|---|
| One-line installer (`install.sh`) | Installed automatically at `/usr/local/bin/cb` |
| `install.sh --docker` / Docker Compose | Not installed — use `docker compose ps` and `docker compose logs -f` instead |

If the copy fails, the installer falls back to telling you to use `systemctl status
circuitbreaker.target` and `journalctl -u 'circuitbreaker-*'` directly.

Running `cb` with no arguments prints the command list.

---

## Configuration

`cb` has no config file of its own. It sources `/etc/circuitbreaker/.env` — the same environment
file the services use — on every run, so it picks up `CB_DATA_DIR`, `CB_DB_PASSWORD`,
`CB_REDIS_PASSWORD`, `CB_PORT`, `CB_FQDN`, and `DOCKER_PROXY_ENABLED` from your install.

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

---

### `cb doctor`

Runs a top-down health check of the whole stack. If you are not root, it re-executes itself under
`sudo` automatically.

```
cb doctor
```

Checks performed, in order:

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

The installer runs `cb doctor` itself as its health-check stage.

---

### `cb logs`

Tails the logs of every Circuit Breaker unit live. It takes no flags and always follows — press
`Ctrl+C` to stop.

```
cb logs
```

Under the hood this is a single `journalctl -f` across the postgres, pgbouncer, redis, nats,
backend, `circuitbreaker-worker@*`, and nginx units.

---

### `cb restart`

Restarts the whole stack through the systemd target, waits a few seconds, then prints `cb status`.

```
cb restart
```

---

### `cb update`

Re-runs the official installer in upgrade mode (`install.sh --upgrade`), fetched from the project
repository. Requires outbound internet access.

```
cb update
```

---

### `cb backup`

Runs `pg_dump` through pgbouncer on `127.0.0.1:6432` as the `breaker` user and writes an
uncompressed SQL dump:

```
cb backup
```

Output path: `${CB_DATA_DIR}/backups/cb-backup-<YYYYmmdd-HHMMSS>.sql`

This is a database dump only — it does not capture uploads, the vault key, or config files. For the
full-state snapshot that does, see [Backup & Restore](backup-restore.md).

---

### `cb version`

Prints the contents of `/opt/circuitbreaker/share/VERSION`, or `unknown` if that file is missing.

```
cb version
```

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

---

## Related

- [Deployment & Security](deployment-security.md)
- [Backup & Restore](backup-restore.md)
