# Plan: Return DB and Mono Image to Production State

## Problem Summary

The mono container currently fails with:

1. **`initdb: command not found`** — Init script calls `initdb` but Debian does not add `/usr/lib/postgresql/15/bin` to PATH.
2. **Postgres never ready during migrate** — Init order runs 10 → 20 → 30 then `supervisord`. Postgres is only started by supervisord, so when 20-migrate runs, Postgres is not running.
3. **`can't find command '/usr/bin/python'`** — Workers and migrate use `python`; the image has only `python3` (and `/usr/local/bin/python3` from the builder).
4. **nginx exit status 1** — Nginx runs as `breaker` (uid 1000) and cannot bind to port 80 (privileged). It may also fail if TLS cert files are missing.
5. **postgres exit status 2** — Data directory was never initialized because initdb failed; supervisord then starts postgres against an empty/missing cluster.

---

## Root Causes

| Issue | Cause |
|-------|--------|
| initdb | Binaries live in `/usr/lib/postgresql/15/bin/`, not in PATH. |
| Migrate waits forever | Postgres is started only after all inits; migrate runs before supervisord. |
| /usr/bin/python | Python 3.12 slim only provides `python3`; no `python` symlink. |
| nginx | Binding to 80 requires root or CAP_NET_BIND_SERVICE; running as breaker fails. |
| postgres (supervisord) | Cluster not initialized because initdb failed. |

---

## Implementation Plan

### 1. Use full path for initdb (10-init-postgres.sh)

- Call `/usr/lib/postgresql/15/bin/initdb` explicitly (Debian Bookworm default is PostgreSQL 15).
- No PATH change required; script remains self-contained.

### 2. Start Postgres before migrate (entrypoint-mono.sh)

- After `ensure_data_dirs` and **only** init script **10** (init-postgres), start Postgres in the background as `breaker` using the same data dir and config that supervisord will use.
- Wait for `pg_isready`.
- Run init scripts **20** (migrate) and **30** (oobe).
- Stop the temporary Postgres process (SIGTERM).
- Then `exec supervisord` so it starts Postgres again against the same data dir.

Flow:

```
ensure_data_dirs → 10-init-postgres → start postgres (bg) → 20-migrate → 30-oobe → stop postgres → exec supervisord
```

### 3. Ensure `python` is available (Dockerfile.mono + supervisord + 20-migrate)

- In **Dockerfile.mono**: add `RUN ln -sf /usr/local/bin/python3 /usr/bin/python` so `python` resolves (workers and 20-migrate use it).
- **supervisord.mono.conf**: workers can keep `command=.../usr/bin/python...` (will work after symlink). Alternatively use `python3` explicitly; symlink keeps existing references working.
- **20-migrate.sh**: inline script uses `python`; no change needed once symlink exists.

### 4. Run supervisord as root; nginx as root (entrypoint + supervisord)

- **entrypoint-mono.sh**: After inits and stopping temporary Postgres, `exec supervisord` as **root** (do not run supervisord from inside `run_as_breaker`). Init scripts and data-dir setup stay as `breaker`.
- **supervisord.mono.conf**: For `[program:nginx]` set `user=root` (or omit so it inherits root). Keep `user=breaker` for postgres, backend-api, workers.

### 5. Nginx TLS when certs missing (optional but recommended)

- If `/data/tls/fullchain.pem` (or privkey) is missing, nginx fails when loading the server block that has `listen 443 ssl` and `ssl_certificate` directives.
- **Option A**: In entrypoint, before starting supervisord, if certs are missing create a self-signed pair under `/data/tls` so nginx always has valid config. Document that production should replace with real certs.
- **Option B**: Ship two nginx configs (HTTP-only vs HTTP+HTTPS) and choose in entrypoint (e.g. copy the right one). More moving parts.
- Prefer **Option A** for simplicity: ensure `/data/tls` exists; if `fullchain.pem` missing, generate a self-signed cert so nginx starts. Real TLS users overwrite with their certs.

---

## File Changes Summary

| File | Change |
|------|--------|
| `Dockerfile.mono` | Add `RUN ln -sf /usr/local/bin/python3 /usr/bin/python`. Optionally ensure PG 15 bin path is predictable (already is). |
| `docker/10-init-postgres.sh` | Use `/usr/lib/postgresql/15/bin/initdb` instead of `initdb`. |
| `docker/entrypoint-mono.sh` | Run 10 only → start Postgres (bg) → run 20, 30 → stop Postgres → exec supervisord as root. Ensure supervisord is not run inside run_as_breaker. Optionally create self-signed TLS if certs missing. |
| `docker/supervisord.mono.conf` | Set `user=root` for `[program:nginx]`. Workers keep using `python` (symlink in image). |
| `docker/nginx.mono.conf` | No change if using Option A (certs created in entrypoint). Optional: document that 443 is only used when certs exist. |

---

## Verification

- Rebuild mono image and run with a fresh `/data` volume.
- Confirm: init-postgres runs, initdb succeeds, migrate runs (Postgres ready), supervisord starts, postgres/backend/workers/nginx all stay up.
- Hit `/api/v1/health` and the frontend; confirm no permission or “command not found” errors in logs.
