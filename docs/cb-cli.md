# cb — Command-Line Tool

`cb` is a small utility that ships with Circuit Breaker and gives you day-to-day operational commands without needing to remember Docker flags or container names.

---

## Installation

How `cb` gets on your system depends on how you installed Circuit Breaker:

| Install method | How to get `cb` |
|---|---|
| One-line installer (`install.sh`) | Installed automatically |
| Docker Compose (from source repo) | Run `make install-cb` after `docker compose up` |
| Manual | `sudo install -Dm755 ./cb /usr/local/bin/cb` from the repo root |

Once installed, `cb help` lists all available commands.

---

## Commands

### `cb status`

Shows the running state of the Circuit Breaker container or service.

```
cb status
```

- **Docker mode**: displays the container name, image, start time, and access URL.
- **Compose mode**: lists all `cb-*` stack containers and their status in a table.
- **Binary mode**: runs `systemctl status circuit-breaker`.

---

### `cb logs [-f]`

Prints the last 100 log lines. Add `-f` to follow in real-time.

```
cb logs
cb logs -f
```

---

### `cb restart`

Restarts Circuit Breaker.

```
cb restart
```

- **Docker mode**: `docker restart <container>`
- **Compose mode**: restarts `cb-backend`, `cb-frontend`, and `cb-caddy` in sequence.
- **Binary mode**: `sudo systemctl restart circuit-breaker`

---

### `cb update`

Pulls the latest image from the registry and recreates the container in place.

```
cb update
```

Available in **Docker mode only** (single-container installs). For compose installs, use:

```bash
docker compose pull && docker compose up -d
```

---

### `cb version`

Prints the installed version.

```
cb version
```

---

### `cb uninstall`

Runs the uninstall script, removing containers, volumes (with confirmation), the `cb` command, and the config directory.

```
cb uninstall
```

---

### `cb vault-recover`

!!! note "Recovery path only"
    You do not need this command during normal operation. The vault key is
    generated automatically when you complete the first-run setup wizard.
    Use `vault-recover` only if the vault ends up in an **uninitialized
    (ephemeral)** state — for example after a crash, accidental deletion of
    the data volume's `.env` file, or a headless deploy with no OOBE.

Generates a fresh Fernet vault key and writes it directly into the container's data volume, then restarts the service to apply it.

```
cb vault-recover
```

The key is never printed to the terminal. If you need to back it up, retrieve it from the data volume:

```bash
# Docker / Compose
docker exec cb-backend cat /app/data/.env   # compose
docker exec circuit-breaker cat /data/.env  # single-container install
```

!!! warning
    If existing encrypted secrets are present (SMTP password, SNMP communities,
    Proxmox tokens), generating a new key will make them unreadable. You will
    need to re-enter them in **Settings** after recovery.

---

## Configuration

`cb` reads its configuration from `~/.circuit-breaker/install.conf`, written by `install.sh` or `make install-cb`. You can inspect it to confirm which mode and container names are active:

```
cat ~/.circuit-breaker/install.conf
```

| Key | Description |
|---|---|
| `CB_MODE` | `docker`, `compose`, or `binary` |
| `CB_CONTAINER` | Primary container name |
| `CB_BACKEND_CONTAINER` | Container that runs the Python app (used for vault commands) |
| `CB_DATA_DIR` | Path to the data directory **inside** the backend container |
| `CB_PORT` | Host port Circuit Breaker is reachable on |
| `CB_IMAGE` | Docker image reference (Docker mode only) |

---

## Related

- [Deployment & Security](deployment-security.md)
- [Backup & Restore](backup-restore.md)
