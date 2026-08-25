# Configuration Reference

Circuit Breaker is configured via environment variables. All variables can be passed to the container at runtime — either in your `docker-compose.yml`, a `.env` file, or with `-e` flags on `docker run`. Native (systemd) installs read the same variables from `/etc/circuitbreaker/.env`.

---

## Environment Variables

### Core

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | _(none)_ | PostgreSQL connection string, used only when `CB_DB_URL` is unset. Must start with `postgresql://` — SQLite was removed in v0.2.0 and the backend refuses to start on any other value. See [PostgreSQL](#postgresql). |
| `CB_JWT_SECRET` | _(required)_ | Signing secret for session JWTs. Minimum 32 characters and must not be a placeholder value; startup fails otherwise. Generate with `python3 -c "import secrets; print(secrets.token_hex(32))"`. `docker-compose.yml` refuses to start when it is unset. |
| `NATS_AUTH_TOKEN` | _(required)_ | Auth token for the internal NATS message bus. Generate with `openssl rand -base64 32`. `docker-compose.yml` refuses to start when it is unset. `CB_NATS_TOKEN` takes precedence when both are set. |
| `CB_SETUP_TOKEN` | _(generated)_ | One-time token required to create the first admin account. If unset, the backend writes a generated token to `CB_DATA_DIR/bootstrap-setup-token` with `0600` permissions. |
| `CB_SETUP_TOKEN_TTL_HOURS` | `24` | First-admin setup-token lifetime in hours. Values are clamped from `1` to `168`. |
| `CB_VAULT_KEY` | _(required for Compose; auto-generated during OOBE on native installs)_ | Fernet encryption key for the credential vault. See [Vault Key](#vault-key). |
| `CB_API_TOKEN` | _(none)_ | **Deprecated.** When it is set, any request to `/api/` that presents it as a `Bearer` token is rejected with `401` unless `CB_LEGACY_AUTH=true` is also set. Use a service account (`POST /api/v1/auth/service-account`) for headless access. It is retained for backward compatibility and has no scheduled removal release. |
| `CB_LEGACY_AUTH` | _(unset)_ | Rollback switch. Set to `true` to temporarily restore the old `CB_API_TOKEN` admin grant while migrating to service accounts. Not intended to be left enabled. |
| `UPLOADS_DIR` | `/data/uploads` | Path for runtime uploads (icons, branding assets). Must be inside the mounted data directory. |
| `CB_DATA_DIR` | `/data` | Backend data directory root inside the container. In Compose the same variable names the **host** directory bind-mounted at `/data` (default `./circuitbreaker-data`). |
| `API_PREFIX` | `/api/v1` | Prefix for all API routes. |
| `CORS_ORIGINS` | _(empty — same origin only)_ | Allowed browser origins, as a JSON array or a comma-separated list. |
| `ANALYTICS_DB_PATH` | _(empty)_ | Optional DuckDB file path for analytics queries. When unset, analytics queries run against the primary PostgreSQL database. |
| `DEBUG` | `false` | Set to `true` to enable verbose backend logging. Not recommended in production. |
| `DEV_MODE` | `false` | Developer mode: SQL logging becomes verbose and unhandled errors return a full stack trace in the response body. Never enable in production. |

### Ports and Image

| Variable | Default | Description |
|---|---|---|
| `CB_PORT` | `80` | Host port published for the container's HTTP listener (container port `8080`). The native installer uses `8088` unless `--port` is given. |
| `CB_PORT_HTTPS` | `443` | Host port published for the container's HTTPS listener (container port `8443`). |
| `CB_TLS_EMAIL` | _(empty)_ | Let's Encrypt account address. Required to request or renew a certificate from the **Certificates** page — the CA uses it for expiry notices, and issuance refuses without it rather than inventing one. Not needed for a self-signed certificate. The native installer writes it from `--email`. See [TLS Certificates](../tls-certificates.md). |
| `CB_IMAGE` | `ghcr.io/blkleg/circuitbreaker:${CB_TAG}` | Full image reference. Override to run a locally built image. |
| `CB_TAG` | `latest` | Image tag used when `CB_IMAGE` is not set. |

### Discovery

| Variable | Default | Description |
|---|---|---|
| `CB_AIRGAP` | `false` | Air-gap mode. When `true`, network scans are refused (HTTP 403) — for offline deployments that only use manual inventory. The same switch exists as `airgap_mode` in Settings. |
| `CB_DOCKER_HOST` | _(empty)_ | Docker API endpoint used for container discovery. The Docker socket is not mounted by default; either apply the `docker/docker-compose.socket.yml` override or point this at a Docker API proxy, e.g. `tcp://docker-socket-proxy:2375`. |

### Message Bus (NATS)

NATS runs inside the application image at `127.0.0.1:4222`. These variables only matter when pointing the backend at an external cluster.

| Variable | Default | Description |
|---|---|---|
| `CB_NATS_URL` | _(none)_ | NATS JetStream connection URL. Takes precedence over `NATS_URL`. |
| `NATS_URL` | `nats://localhost:4222` | Fallback name for the same URL. The image and the native installer both set `nats://127.0.0.1:4222`. |
| `NATS_USER` / `NATS_PASSWORD` | _(empty)_ | Username/password credentials for an external NATS cluster. |
| `NATS_TLS` | _(empty)_ | Set to `true` (or `1`/`yes`) to connect to NATS over TLS. |

### Production Dependency Safety

| Variable | Default | Description |
|---|---|---|
| `CB_REDIS_URL` | `redis://localhost:6379/0` | Redis URL used for shared rate limits, session/dependency state, telemetry cache, and pub/sub. Production startup fails closed when Redis is unavailable unless degraded mode is explicitly enabled. |
| `CB_RATE_LIMIT_STORAGE_URL` | _(derived from `CB_REDIS_URL`)_ | Optional override for application rate-limit storage. Use Redis in production; `memory://` is accepted only for tests or explicitly degraded operation. |
| `CB_RATE_LIMIT_RPM` | `600` | Per-tenant request budget per 60-second rolling window, enforced by the tenant rate-limit middleware. Requires Redis. |
| `CB_TRUSTED_PROXY_CIDRS` | `127.0.0.1/32,::1/128` | Comma-separated (a JSON array is also accepted). CIDRs for reverse proxies whose `X-Forwarded-For` value may be trusted for rate-limit identity. Requests from other peers are keyed by the socket peer address. |
| `CB_EGRESS_PROXY_URL` | _(empty)_ | HTTP forward proxy used by public outbound clients such as webhooks, threat-feed downloads, and custom S3 backup endpoints. The proxy should block link-local/metadata and non-approved destinations. Required in strict production unless `CB_ALLOW_DIRECT_EGRESS=true`. An invalid value fails startup even when `CB_ALLOW_DIRECT_EGRESS=true`. |
| `CB_ALLOW_DIRECT_EGRESS` | `true` in `docker-compose.yml`, `docker/.env.example`, `apps/backend/.env.example`, and the installer-generated `/etc/circuitbreaker/.env`; `false` in code | Records that this host has no forward proxy, so an empty `CB_EGRESS_PROXY_URL` is a decision rather than an omission. Waives that one requirement and nothing else — outbound requests are still checked by the shared SSRF/URL policy, and Redis, NATS, rate-limit storage and secrets still fail closed. Set to `false` once a proxy is configured. |
| `CB_ALLOW_DEGRADED_DEPENDENCIES` | `false` | Test/emergency switch. When `true` it waives exactly four gates: missing Redis, missing NATS, `memory://` rate-limit storage, and the egress-proxy requirement (including an invalid `CB_EGRESS_PROXY_URL`). It does not waive the secret checks below. |

Strict production startup treats empty values as missing. Set `CB_ALLOW_DEGRADED_DEPENDENCIES=true`
only for local tests or an approved break-glass window; it permits insecure degraded behavior and
should not be left enabled.

The JWT/session signing secret and the vault key are validated on every startup regardless of these
flags. Each must be at least 32 characters and must not be one of the rejected placeholder values
(`change_me`, `changeme`, `placeholder`, `todo`, `test`, `secret`, `password`). A failure here aborts
startup; no flag waives it.

### First-Admin Setup Token

Fresh installs require a setup token before the first admin can be created. For production, set
`CB_SETUP_TOKEN` to a high-entropy value before first start and enter that value in the first-run
wizard. The token must be at least 16 characters.

If `CB_SETUP_TOKEN` is not set, Circuit Breaker generates a token during the first bootstrap status
check and writes it to:

```text
CB_DATA_DIR/bootstrap-setup-token
```

The file is written with owner-only permissions (`0600`). The public `/api/v1/bootstrap/status`
response only reports that a token is required and when it expires; it never includes the token.

The default token lifetime is 24 hours. Set `CB_SETUP_TOKEN_TTL_HOURS` before setup to choose a value
from 1 to 168 hours. Failed attempts do not consume the token. A successful bootstrap consumes it and
replay attempts receive `409 Bootstrap already completed`.

### WebSockets

| Variable | Default | Description |
|---|---|---|
| `CB_WS_REQUIRE_WSS` | _(unset)_ | Set to `true` (or `1`/`yes`) to reject WebSocket connections that do not arrive over WSS. Use when every client reaches the app over HTTPS. |

Certificate handling is described under [TLS / HTTPS](#tls-https) below.

### PostgreSQL

| Variable | Default | Description |
|---|---|---|
| `CB_DB_URL` | _(none — embedded PostgreSQL)_ | Full PostgreSQL connection string, e.g. `postgresql://breaker:pass@db-host:5432/circuitbreaker`. Leave unset to use the PostgreSQL embedded in the application image. Takes precedence over `DATABASE_URL`. |
| `CB_DB_PASSWORD` | _(required)_ | Password for the embedded PostgreSQL `breaker` user. `docker-compose.yml` fails immediately when it is unset. |
| `CB_DB_POOL_URL` | _(falls back to `CB_DB_URL`)_ | PgBouncer connection string (transaction mode, port 6432). When it differs from `CB_DB_URL`, the SQLAlchemy pool shrinks to 5/5 to avoid double-pooling. |
| `DB_POOL_SIZE` | `20` (`5` when `CB_DB_POOL_URL` is set) | SQLAlchemy connection pool size. Lower it on Raspberry Pi / low-memory hosts. |
| `DB_MAX_OVERFLOW` | `20` (`5` when `CB_DB_POOL_URL` is set) | Connections allowed above the pool size before requests queue. |

### Native install (`/etc/circuitbreaker/.env`)

The native installer writes `/etc/circuitbreaker/.env` and the systemd units read it. It contains the
generated secrets — `CB_JWT_SECRET`, `CB_VAULT_KEY`, `CB_DB_PASSWORD`, `CB_REDIS_PASSWORD`,
`CB_NATS_TOKEN` — which must not be hand-edited: regenerating them makes existing encrypted data and
sessions unreadable. Alongside them it sets:

| Variable | Value written by the installer | Purpose |
|---|---|---|
| `CB_DB_URL` | `postgresql://breaker:…@127.0.0.1:5432/circuitbreaker` | Local PostgreSQL |
| `CB_DB_POOL_URL` | `postgresql://breaker:…@127.0.0.1:6432/circuitbreaker` | Local PgBouncer |
| `CB_REDIS_URL` | `redis://:…@127.0.0.1:6379/0` | Local Redis |
| `CB_NATS_URL`, `NATS_URL` | `nats://127.0.0.1:4222` | Local NATS |
| `CB_DATA_DIR` | Install data path | Data root (uploads, TLS material, logs) |
| `CB_UPLOADS_DIR`, `UPLOADS_DIR` | `${CB_DATA_DIR}/uploads` | Upload directory — the backend reads `UPLOADS_DIR` |
| `CB_LOG_DIR` | `${CB_DATA_DIR}/logs` | Log directory |
| `CB_STATIC_DIR` | `/opt/circuitbreaker/share/frontend` | Built frontend assets |
| `CB_SHARE_DIR` | `/opt/circuitbreaker/share` | Packaged assets, including the `VERSION` file the backend reports |
| `CB_ALEMBIC_INI` | `/opt/circuitbreaker/share/backend/alembic.ini` | Alembic config used to run migrations |
| `CB_AGENT_BINARIES_DIR` | `/opt/circuitbreaker/agent-binaries` | Agent binaries offered for download |
| `CB_PORT` | `8088` unless `--port` was given | HTTP port for the bundled nginx |
| `CB_FQDN`, `CB_APP_URL` | From the install flags | Hostname and base URL used in generated links |
| `CB_ENV` | `production` | Deployment environment marker |

### `config.toml`

Before reading the environment, the backend looks for a `config.toml` in this order and uses the
first file it finds:

```text
$CB_CONFIG
/etc/circuit-breaker/config.toml
~/.config/circuitbreaker/config.toml
./config.toml
```

A value from the file is applied only when the matching environment variable is unset, so environment
variables always win. The recognised keys are:

| TOML key | Environment variable |
|---|---|
| `server.host` | `CB_HOST` |
| `server.port` | `CB_PORT` |
| `database.url` | `CB_DB_URL` |
| `database.pool_size` | `DB_POOL_SIZE` |
| `database.max_overflow` | `DB_MAX_OVERFLOW` |
| `redis.url` | `CB_REDIS_URL` |
| `nats.url` | `CB_NATS_URL` |
| `nats.auth_token` | `NATS_AUTH_TOKEN` |
| `security.vault_key` | `CB_VAULT_KEY` |
| `security.cors_origins` | `CORS_ORIGINS` |
| `discovery.docker_host` | `CB_DOCKER_HOST` |
| `discovery.proxmox_url` | `CB_PROXMOX_URL` |
| `paths.data_dir` | `CB_DATA_DIR` |
| `paths.log_dir` | `CB_LOG_DIR` |
| `paths.static_dir` | `STATIC_DIR` |
| `paths.alembic_ini` | `CB_ALEMBIC_INI` |
| `updates.check_on_startup` | `CB_UPDATE_CHECK` |

---

## Vault Key

The vault key is a [Fernet](https://cryptography.io/en/latest/fernet/) symmetric encryption key used to encrypt credentials stored in the database (SMTP passwords, Proxmox API tokens, SNMP community strings).

### Auto-generated (native / OOBE installs)

If `CB_VAULT_KEY` is not set, Circuit Breaker generates a key during the first-run wizard and writes it to `/data/.env` inside the data directory. The key is loaded from this file on subsequent starts, and the container entrypoint adopts a rotated key from that file automatically.

This path applies to native and OOBE installs only. The shipped `docker-compose.yml` requires `CB_VAULT_KEY` up front and refuses to start without it.

**This key is shown once during the [first-run wizard](first-run.md).** Back it up before closing the wizard.

### Pre-seeding a key

Generate a key before first launch and set it in your environment:

```bash
openssl rand -base64 32
```

In `docker-compose.yml`:
```yaml
environment:
  - CB_VAULT_KEY=<your-key-here>
```

In a `.env` file:
```
CB_VAULT_KEY=<your-key-here>
```

Pre-seeding is required for Compose installs and recommended everywhere else — it ensures the key survives a data-directory recreation and avoids the vault key ceremony during OOBE.

### Recovery

There is no command that recovers a lost vault key. The key is the only thing that can decrypt
stored credentials, so if it is gone, the encrypted values are unrecoverable.

If the key is lost, restore `CB_VAULT_KEY` from a snapshot or your own secret store, restart, and the
existing credentials decrypt as before. If no copy of the key exists, set a new one, restart, and
re-enter every stored credential in **Settings** — the old ciphertext cannot be salvaged.

See [Backup & Restore](../backup-restore.md) for the snapshot procedure.

---

## Volumes and Persistence

The shipped `docker-compose.yml` declares no named volumes. The container has exactly two mounts:

| Mount | Stores | Notes |
|---|---|---|
| `${CB_DATA_DIR:-./circuitbreaker-data}:/data` | Everything persistent | Bind mount. Must be preserved across updates. |
| `/run/circuitbreaker:/run/circuitbreaker` | `cb-helperd` socket | Optional host-side discovery helper. Harmless if `cb-helperd` is not installed — the path simply will not exist inside the container. |

Everything the install needs lives under `/data`. The entrypoint creates these on first boot:

| Path | Stores |
|---|---|
| `/data/pgdata` | PostgreSQL data files (embedded PostgreSQL) |
| `/data/uploads` | Icons, branding assets, and other user uploads |
| `/data/nats` | NATS JetStream state |
| `/data/redis` | Redis persistence |
| `/data/tls` | `fullchain.pem` and `privkey.pem` used by the HTTPS listener |
| `/data/.env` | Vault key written by OOBE and by key rotation |

**Backup priority:** back up the `CB_DATA_DIR` directory together with `CB_VAULT_KEY`. That pair covers the whole install. If you restore the database without the matching vault key, all encrypted credentials become unreadable. See [Backup & Restore](../backup-restore.md).

### Data directory vs database (full reset)

When **CB_DB_URL** points to an external host (e.g. `postgresql://...@postgres:5432/circuitbreaker`), **users and sessions live only in that database**. Wiping the **CB_DATA_DIR** bind mount does **not** touch that database. Changing or wiping CB_DATA_DIR will not log you out or remove your account; the app will still use the same Postgres and the same identity.

**Full reset with external Postgres** requires one of:

- **Drop and recreate the database** that CB_DB_URL points to: connect to the `postgres` database and run `DROP DATABASE circuitbreaker;` then `CREATE DATABASE circuitbreaker;`, then restart the app so migrations run.
- **Use the embedded Postgres** so the DB lives under CB_DATA_DIR: leave CB_DB_URL unset. Then `docker compose down` followed by deleting the CB_DATA_DIR directory (e.g. `rm -rf ./circuitbreaker-data`) also removes the database and gives you a fresh identity.

---

## TLS / HTTPS

The application image terminates TLS itself with nginx: HTTP on container port `8080` and HTTPS on container port `8443`, published on the host as `CB_PORT` (default `80`) and `CB_PORT_HTTPS` (default `443`).

### Self-signed certificate (default)

On startup, if `${CB_DATA_DIR}/tls/fullchain.pem` or `${CB_DATA_DIR}/tls/privkey.pem` is missing, a self-signed certificate is generated into that directory — an EC certificate with `CN=localhost` in the container image, or an RSA certificate with `CN` set to `--fqdn` plus a SAN for the server IP on native installs. Existing files are never overwritten.

### Using your own certificate

Place your PEM pair at:

```text
${CB_DATA_DIR}/tls/fullchain.pem
${CB_DATA_DIR}/tls/privkey.pem
```

and restart. A native install run with both `--fqdn` and `--email` validates that the FQDN resolves to this server and expects Let's Encrypt certificates at those same paths; if DNS validation fails it falls back to a self-signed certificate.

### Let's Encrypt from the application

You do not have to run certbot yourself. With `CB_TLS_EMAIL` set and a publicly-resolvable domain, the **Certificates** page issues and renews Let's Encrypt certificates over HTTP-01 or DNS-01, and **Activate** writes the pair to the paths above and reloads nginx. Renewal of the active certificate re-activates it automatically. See [TLS Certificates](../tls-certificates.md) for the requirements of each challenge type and for why a LAN-only install cannot use this at all.

### Certificate warnings

Because the generated certificate is self-signed, browsers warn on first visit. Your options are:

- Accept the browser warning — acceptable for LAN-only access.
- Replace the certificate with one issued for your domain, as described above.
- For scripted clients, pass the certificate explicitly, e.g. `curl --cacert fullchain.pem https://<host>/api/v1/health`.

---

## Related

- [Deployment & Security](../deployment-security.md) — hardening, vault best practices
- [Remote Access & Tunnels](../remote-access.md)
- [Backup & Restore](../backup-restore.md)
- [TLS Certificates](../tls-certificates.md) — issuing, renewing and activating certificates
