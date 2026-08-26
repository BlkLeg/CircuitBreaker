# Configuration Precedence and Environment Catalogue

Circuit Breaker reads configuration from five places. This page states the order they win in, and
then catalogues **every environment variable the code actually reads**, with its default, its type
and what it changes.

[Configuration Reference](../installation/configuration.md) is the task-oriented companion: how to
set the common values for each install method, with worked examples. This page is the exhaustive
one — if a variable appears in the source, it appears here.

---

## Precedence order

From highest to lowest. The first tier that supplies a value wins; lower tiers fill gaps.

| # | Tier | Where it comes from | Applies to |
|---|---|---|---|
| 1 | Command-line flag | `circuit-breaker --port 9090`, `--host`, `--workers`, `--ssl-certfile`, `--ssl-keyfile` | The handful of runtime options the launcher exposes as flags |
| 2 | Environment | The process environment: `/etc/circuitbreaker/.env` (native), `/etc/circuit-breaker/circuit-breaker.env` (deb/rpm/apk), the Compose `environment:` block or `.env`, `docker run -e` | Everything in the catalogue below |
| 3 | `config.toml` | `$CB_CONFIG`, then `/etc/circuit-breaker/config.toml`, then `~/.config/circuitbreaker/config.toml`, then `./config.toml` — first file found wins | The 17 keys in the [TOML key map](#configtoml-key-map) |
| 4 | Native `config.yaml` | `--config`, else `$CB_CONFIG_PATH`, else `/etc/circuit-breaker/config.yaml` | The runtime options `app/start.py` resolves |
| 5 | Code default | The value compiled into the application | Everything with a default in the catalogue |

The mechanism, not a promise: `app/core/config_toml.py:load_config_toml()` writes each mapped key
into `os.environ` **only when that name is not already set**, and it runs before
`app/start.py:configure_runtime()` resolves anything. So tier 3 is invisible to tier 2 — an
environment variable always shadows the file — and `_get_option()` then applies tiers 1, 2, 4 and 5
in that order.

### Two settings have a database tier

Two secrets are resolved from PostgreSQL as well, and the database can outrank the environment:

| Secret | Resolution order |
|---|---|
| JWT/session signing secret | `app_settings.jwt_secret` **first**, then `CB_JWT_SECRET`. `settings_service` generates and stores one when the column is empty, so a native install whose env file never mentions the variable is correctly configured. |
| Vault key (`CB_VAULT_KEY`) | `CB_VAULT_KEY`, cross-checked against `app_settings.vault_key_hash` — a valid-but-stale key is **rejected and fallen through**, not used — then `$CB_DATA_DIR/.env`, then the legacy plaintext `app_settings.vault_key` column, which is migrated out to `$CB_DATA_DIR/.env` and cleared on load. |

A vault key that is not a real Fernet key (32 random bytes, URL-safe base64, 44 characters) is
discarded **silently** at every tier: the server falls through to the next tier or generates a
fresh key, and your configured key is never the key in use. `cb config validate` calls the
loader's own predicate rather than restating the rule, so it catches this.

### Runtime settings that live only in the database

A third group is not environment configuration at all — it is stored in `app_settings` and edited
in **Settings** in the UI. The overlap worth knowing:

| Setting | Environment equivalent | Interaction |
|---|---|---|
| `airgap_mode` | `CB_AIRGAP` | Either one being on is enough |
| `rate_limit_profile` | — | Selects the per-route limit table; no environment variable |
| `client_hash_salt` | `CB_CLIENT_SALT` | Environment wins |
| `audit_log_retention_days`, `discovery_retention_days`, `db_backup_retention_days`, `max_concurrent_scans`, `concurrent_sessions` | — | Database only |

---

## Validating a configuration before you use it

```bash
cb config validate
```

It runs the backend's own validator, so `cb` never develops a second, drifting opinion about what a
valid configuration is. The pass is **offline by construction** — it replaces `socket.getaddrinfo`
for the duration, so nothing in it can reach Postgres, Redis, NATS or a resolver — and it reports
which tier each setting was resolved from. Secret *values* are never printed; connection strings
have their userinfo redacted.

Exit status is `0` for valid, `1` for invalid. What it can and cannot see:

- **Sees:** the environment, `config.toml`, and `$CB_DATA_DIR/.env` for the vault key.
- **Cannot see, and says so:** the `app_settings` database tier, unless you ask for it with
  `--database`. An absent secret is reported as a *warning* naming the tier that may still hold it;
  a secret that is present and bad is an *error*, because no later tier can rescue it.
- **Defers, and names what it deferred:** the DNS/SSRF screen on `CB_EGRESS_PROXY_URL`. Syntax,
  scheme, userinfo and port are checked offline; resolution happens at startup.

The direct entry points — also the only way to pass the validator's own flags, since the `cb`
wrapper forwards no arguments beyond `validate`:

| Install shape | Command |
|---|---|
| Source / container | `python -m app.cli config validate [--config PATH] [--set NAME=VALUE ...] [--database]` |
| Packaged binary | `circuit-breaker --config-validate [--config PATH]` |

`--set NAME=VALUE` overrides one setting for that pass at the highest precedence — above the
environment, which is above `config.toml` — so you can answer "would it be valid if I changed this?"
without editing anything. `NAME` is either an environment variable (`CB_PORT=9090`) or the
`config.toml` key that maps to one (`server.port=9090`). Repeatable.

`--database` additionally reads the `app_settings` tier and reports the conflicts only it can see: a
`CB_JWT_SECRET` shadowed by the database column, or a vault key the server would reject as stale. It
opens a database connection; every other pass is offline.

---

## Environment catalogue

Every variable below is read by the application at runtime. Names in the same row are aliases for
one setting, listed in the order the code prefers them.

!!! note "Aliases are not decoration"
    Several settings accept both a `CB_`-prefixed and an unprefixed name. Where both are set the
    `CB_` form wins. Use one consistently — a deployment with `CB_DB_URL` in one file and
    `DATABASE_URL` in another is a debugging session waiting to happen.

### Identity and version

| Variable | Type | Default | Effect |
|---|---|---|---|
| `APP_VERSION` | string | resolved from the `VERSION` file | Overrides the version the app reports in the UI, API and `User-Agent`. Set by the Docker build. |
| `CB_VERSION` | string | `unknown` | The version recorded in a snapshot manifest and checked when verifying one. |
| `CB_SHARE_DIR` | path | unset | Where the packaged `VERSION`, frontend and Alembic tree live. Searched first when resolving the version. |
| `CB_INSTALL_METHOD` | string | auto-detected | Declares how this instance was installed; shown in diagnostics and recorded in snapshots. |
| `CB_INSTALL_MODE` | string | `unknown` | Recorded in the snapshot manifest so a restore knows what layout produced the archive. |
| `APPIMAGE` | path | unset (set by the AppImage runtime) | Presence makes install-method detection report an AppImage run. |

### Listener and process

Each of these has a command-line flag that outranks it; see [Precedence order](#precedence-order).

| Variable | Type | Default | Effect |
|---|---|---|---|
| `HOST` | string | `127.0.0.1` | Address uvicorn binds. Flag: `--host`. |
| `PORT` | int | `8080` | Port uvicorn binds. Flag: `--port`. Note this is the **backend** port; the native installer puts nginx on `CB_PORT` in front of a backend on `8000`. |
| `UVICORN_WORKERS` | int | `1` | Uvicorn worker processes. Flag: `--workers`. More than one makes the shared-Redis session cache coherence path load-bearing. |
| `CB_TLS_ENABLED` | bool | `false` | Assert that the backend itself should serve HTTPS. Fails startup unless both cert and key paths are also set. |
| `CB_TLS_CERT_FILE` | path | unset | TLS certificate for the backend listener. Flag: `--ssl-certfile`. |
| `CB_TLS_KEY_FILE` | path | unset | TLS private key for the backend listener. Flag: `--ssl-keyfile`. |
| `CB_CONFIG_PATH` | path | `/etc/circuit-breaker/config.yaml` | Default for the `--config` flag (the native YAML tier). |
| `CB_CONFIG` | path | unset | First candidate in the `config.toml` search order. |
| `API_PREFIX` | string | `/api/v1` | Route prefix. Changing it is untested. |
| `CB_RUN_INPROCESS_WORKERS` | bool | `true` | Run the background workers inside the API process. Set `false` when dedicated worker processes are deployed, or work is executed twice. |

### Paths and storage

| Variable | Type | Default | Effect |
|---|---|---|---|
| `CB_DATA_DIR` | path | `/data` in containers; `./data` for several callers; `/var/lib/circuitbreaker` for the backup module | Root of all persistent state: `pgdata`, `uploads`, `nats`, `redis`, `tls`, `certs`, `.env`. The differing fallbacks are per-module; every shipped deployment sets this explicitly. |
| `UPLOADS_DIR` | path | `data/uploads`, or `$CB_DATA_DIR/uploads` when the launcher resolves it | Where uploaded icons, branding and document images are written. Must be inside the persisted data directory. |
| `STATIC_DIR` | path | `../frontend/dist` | Built frontend assets. Absent or empty means the API runs headless — the static mounts are skipped. |
| `BACKUP_DIR` | path | `$CB_DATA_DIR/backups` | Where snapshots are written. Read **at import time**, which is why `cb snapshot create --out` sets it before the builder is imported. |
| `ANALYTICS_DB_PATH` | path | empty | Optional DuckDB file for analytics queries. Empty means analytics run on the primary PostgreSQL engine. |
| `CB_AGENT_BINARIES_DIR` | path | `/opt/circuitbreaker/agent-binaries` | Agent binaries served for enrollment and self-update. |
| `CB_ALEMBIC_INI` / `ALEMBIC_CONFIG` | path | discovered relative to the app tree | Alembic config used for migrations. |
| `CB_DOCS_SEED_FILE` | path | the bundled `DocsPage.md` | Markdown seeded into the in-app documentation on first start. |
| `CB_HELPER_SOCKET_PATH` | path | `/run/circuitbreaker/helper.sock` | Unix socket for the optional host-side discovery helper. Harmless when the helper is not installed. |
| `CB_NGINX_PID_FILE` | path | the platform default | PID file signalled when an activated certificate needs nginx to reload. |
| `CB_LOG_DIR` | path | — | Written by the installer and mapped from `paths.log_dir`; the backend process does not read it. Listed here because operators find it in their env file. |

### Database

| Variable | Type | Default | Effect |
|---|---|---|---|
| `CB_DB_URL` / `DATABASE_URL` | URL | none — **required** | PostgreSQL connection string. Must begin `postgresql://`; SQLite was removed in v0.2.0 and startup fails on anything else. The launcher exits with an actionable error when neither is set. |
| `CB_DB_POOL_URL` | URL | falls back to the database URL | PgBouncer URL (transaction mode, port 6432). When it differs from `CB_DB_URL` the SQLAlchemy pool shrinks to 5/5 to avoid double-pooling, and asyncpg statement caching is disabled. |
| `DB_POOL_SIZE` | int | `20`, or `5` when a distinct pool URL is set | SQLAlchemy pool size. Lower it on low-memory hosts. |
| `DB_MAX_OVERFLOW` | int | `20`, or `5` when a distinct pool URL is set | Connections allowed above the pool size before callers queue. |
| `CB_AUTO_MIGRATE` | bool | `true` | Run Alembic on startup. The launcher sets it to `false` for spawned workers after it has migrated once, so workers cannot re-run migrations concurrently. |
| `CB_DISABLE_LEGACY_ALEMBIC_STAMP` | bool | `false` | Suppresses the compatibility stamp applied to databases from before the current migration chain. |
| `CB_REQUIRE_TIMESCALE` | bool | `false` | Require the TimescaleDB extension. When unset, hypertable migrations are skipped on a plain PostgreSQL and telemetry uses ordinary tables. |

### Redis

| Variable | Type | Default | Effect |
|---|---|---|---|
| `CB_REDIS_URL` / `REDIS_URL` | URL | `redis://localhost:6379/0` | Shared rate limits, session-revocation coherence, telemetry cache and pub/sub. Startup fails closed when Redis is unreachable unless degraded mode is explicitly enabled. |
| `CB_REDIS_PASSWORD` | secret | unset | Password used when the URL carries none. |
| `CB_REDIS_PASSWORD_FILE` | path | `/data/.redis_pass` | File read for the password when the variable is unset. |
| `CB_RATE_LIMIT_STORAGE_URL` / `RATE_LIMIT_STORAGE_URL` | URL | derived from the Redis URL | Storage for the per-route limiter. **Must not resolve to `memory://` in production** — startup refuses it. |

### NATS

| Variable | Type | Default | Effect |
|---|---|---|---|
| `CB_NATS_URL` / `NATS_URL` | URL | `nats://localhost:4222` | Internal bus for worker dispatch, notifications and event fan-out. Startup fails closed when NATS is unreachable unless degraded mode is enabled. |
| `CB_NATS_TOKEN` / `NATS_AUTH_TOKEN` | secret | empty | Token authentication. Required in both shipped install paths — Compose refuses to start without it, and the native installer generates one. |
| `NATS_USER`, `NATS_PASSWORD` | secret | empty | User/password credentials for an external cluster; embedded into the connection URL by the client. |
| `NATS_TLS` | bool | `false` | Connect with `tls://` and TLS enabled. The server must be configured for TLS separately. |

### Secrets and authentication

| Variable | Type | Default | Effect |
|---|---|---|---|
| `CB_JWT_SECRET` | secret | none; the database tier supplies or generates one | Signs session JWTs. At least 32 characters and not a placeholder, or startup fails. `app_settings.jwt_secret` outranks it — see [the database tier](#two-settings-have-a-database-tier). |
| `CB_VAULT_KEY` | secret | none; generated during first-run if absent everywhere | Fernet key encrypting stored credentials (SMTP, Proxmox tokens, SNMP strings, iDRAC/iLO). Must be a real Fernet key. Losing it makes every encrypted value unrecoverable. |
| `CB_CLIENT_SALT` | string | `circuitbreaker-salt-v1`, else `app_settings.client_hash_salt` | Salt for the browser-side PBKDF2 password pre-hash. Must match what the frontend uses. |
| `CB_SETUP_TOKEN` | secret | generated to `$CB_DATA_DIR/bootstrap-setup-token` (mode `0600`) | One-time token gating creation of the first administrator. At least 16 characters. |
| `CB_SETUP_TOKEN_TTL_HOURS` | int | `24`, clamped to 1–168 | Lifetime of that token. |
| `CB_API_TOKEN` | secret | unset | **Deprecated and rejected.** A Bearer token matching it is answered `401`, and startup logs a removal warning. Use a service account. |
| `CB_LEGACY_AUTH` | bool | `false` | Temporary rollback that restores the old `CB_API_TOKEN` admin grant. Not for long-term operation. |

The placeholder values rejected for any secret: `change_me`, `changeme`, `placeholder`, `todo`,
`test`, `secret`, `password`. No flag waives the secret checks.

### Network trust and egress

| Variable | Type | Default | Effect |
|---|---|---|---|
| `CB_TRUSTED_PROXY_CIDRS` / `TRUSTED_PROXY_CIDRS` | CIDR list | `127.0.0.1/32,::1/128` | Peers whose `X-Forwarded-For`, `-Proto` and `-Host` are believed. Comma-separated or a JSON array. Invalid entries are dropped with a warning rather than failing startup. Getting it wrong collapses rate limiting onto the proxy's IP and makes `CB_WS_REQUIRE_WSS` reject everything. |
| `CORS_ORIGINS` | list | empty — same-origin only | Allowed browser origins. JSON array or comma-separated. A literal `*` is dropped. |
| `CB_EGRESS_PROXY_URL` / `EGRESS_PROXY_URL` | URL | empty | Forward proxy for public outbound HTTP (webhooks, threat feeds, the release check, custom S3 endpoints). An invalid value fails startup even under degraded mode. |
| `CB_ALLOW_DIRECT_EGRESS` | bool | `false` in code; `true` in every shipped template | Records that this host has no forward proxy. Waives the proxy requirement **and nothing else** — the SSRF/URL policy still applies to every public request. |
| `CB_ALLOW_DEGRADED_DEPENDENCIES` | bool | `false` | Break-glass. Waives exactly four gates: missing Redis, missing NATS, `memory://` rate-limit storage, and the egress-proxy requirement. Never waives the secret checks. |
| `CB_AIRGAP` / `AIRGAP` | bool | `false` | Refuses network scans (`403`) and opens no socket for the release check. Equivalent to the `airgap_mode` switch in Settings; either is enough. |
| `CB_UPDATE_CHECK` / `UPDATE_CHECK` | bool | `true` | The daily GitHub release check. `false` stops the socket being opened at all. |
| `CB_WS_REQUIRE_WSS` | bool | `false` | Reject WebSocket handshakes that are not secure. Set `CB_TRUSTED_PROXY_CIDRS` correctly first, or every connection behind a TLS-terminating proxy is refused. |

### Bounds and concurrency

Defaults are chosen so the process degrades by refusing work rather than by growing without limit.
The operational reading of these — which profile needs which value — is in
[Sizing profiles](../operations/sizing-profiles.md).

| Variable | Type | Default | Effect |
|---|---|---|---|
| `CB_RATE_LIMIT_RPM` | int | `600` | Tenant-scoped sliding-window budget per 60 s. Inert on the 1.0 single-tenant path. |
| `CB_WS_MAX_CONNECTIONS` | int | `50` | Global cap on the shared WebSocket manager (discovery and agent presence). |
| `CB_WS_MAX_PER_IP` | int | `5` | Per-IP cap on the same manager. |
| `CB_WS_MON_MAX_CONNECTIONS` / `CB_WS_MON_MAX_PER_IP` | int | `100` / `10` | Monitor stream caps. |
| `CB_WS_TELEM_MAX_CONNECTIONS` / `CB_WS_TELEM_MAX_PER_IP` | int | `100` / `10` | Telemetry stream caps. |
| `CB_WS_TOPO_MAX_CONNECTIONS` / `CB_WS_TOPO_MAX_PER_IP` | int | `50` / `5` | Topology stream caps. |
| `CB_CIRCUIT_BREAKER_MAX_ENTRIES` | int | `500` | Maximum tracked endpoints in the outbound circuit breaker. |
| `CB_CIRCUIT_BREAKER_TTL_SEC` | int | `3600` | How long an entry survives without traffic. |
| `CB_EVENTS_RETENTION_HOURS` | int | `24` | `max_age` of the NATS events stream. |
| `CB_ALERT_DEBOUNCE_S` | int | `60` | Notification de-duplication window. |
| `CB_NOTIFICATION_RETRIES` | int | `2` | Delivery retries per notification. |

### Monitoring and probes

| Variable | Type | Default | Effect |
|---|---|---|---|
| `CB_MONITOR_SCHED_TICK_S` | float | `1.0` | Scheduler tick interval. |
| `CB_MONITOR_SCHED_BATCH` | int | `200` | Checks claimed per tick. |
| `CB_MONITOR_SCHED_PER_VANTAGE` | int | `50` | Per-vantage claim ceiling, so one agent cannot starve the rest. |
| `CB_MONITOR_SCHED_OVERSAMPLE` | int | `1000` | Rows examined when selecting a batch. |
| `CB_MONITOR_POLL_PARALLEL` | int | `50` | Concurrent server-side checks. |
| `CB_MONITOR_POLL_FETCH` | int | `50` | Messages fetched per poll-worker pull. |
| `CB_MONITOR_POLL_MAX_AGE_S` | int | `300` | `max_age` of the poll stream — a message older than this is dropped rather than executed late. |
| `CB_MONITOR_PROBE_FETCH` | int | `50` | Messages fetched per probe-dispatch pull. |
| `CB_MONITOR_PROBE_MAX_AGE_S` | int | `60` | `max_age` of the remote-probe stream. |
| `CB_MONITOR_PROBE_DEADLINE_HEADROOM_S` | float | `10` | Headroom subtracted when computing a probe's deadline. |
| `CB_MONITOR_PROBE_DEADLINE_MIN_S` | float | `20` | Floor for that deadline. |
| `CB_MONITOR_PROBE_BUDGET_MAX_S` | float | `600` | Ceiling for a single probe's execution budget. |
| `CB_MONITOR_PROBE_RETENTION_DAYS` | int | `7` | How long probe-run records are kept. |
| `CB_PROBE_READINESS_MAX_AGE_S` | int | `2700` | How stale an agent's readiness may be before it stops being probe-eligible. |

### Discovery and telemetry

| Variable | Type | Default | Effect |
|---|---|---|---|
| `CB_DISCOVERY_DISPATCH_DEADLINE_S` | int | `900` | How long a dispatched discovery job may remain outstanding. |
| `CB_DISCOVERY_RECONCILE_INTERVAL_S` | int | `60` | Reconciliation sweep interval for agent discovery. |
| `CB_DISCOVERY_READINESS_MAX_AGE_S` | int | inherits `CB_PROBE_READINESS_MAX_AGE_S` (`2700`) | Readiness staleness ceiling for discovery eligibility. |
| `CB_DOCKER_HOST` | URL | empty | Docker API endpoint for container discovery. The socket is not mounted by default; use the socket overlay or a Docker API proxy. |
| `CB_TELEMETRY_POLL_SECONDS` | int | `30`, floored at `10` | Telemetry collection interval. |
| `CB_TELEMETRY_DEVICE_TIMEOUT_SECONDS` | int | `20`, floored at `5` | Per-device timeout. |
| `CB_TELEMETRY_MAX_PARALLEL` | int | `8`, floored at `1` | Devices polled concurrently. |
| `PROXMOX_NODE_POLL_SECONDS` | int | `30` | Proxmox node poll interval. |
| `PROXMOX_VM_POLL_SECONDS` | int | `120` | Proxmox guest poll interval. |
| `PROXMOX_RRD_POLL_SECONDS` | int | `300` | Proxmox RRD history poll interval. |

### Diagnostics

| Variable | Type | Default | Effect |
|---|---|---|---|
| `DEBUG` | bool | `false` | Verbose backend logging. |
| `DEV_MODE` | bool | `false` | Verbose SQL logging **and full stack traces in error responses**. Never enable in production. |
| `CB_OTEL_ENDPOINT` | URL | empty | OTLP endpoint. Empty disables OpenTelemetry export entirely. |
| `CB_HEALTH_CACHE_TTL_S` | float | `2.0` | How long a dependency verdict may be reused by the health guard. Deliberately short: it bounds how long a write can be admitted against a database that has just gone away, and how many probes a burst of writes can trigger. |
| `CB_TLS_EMAIL` | email | empty | ACME account address. Certificate issuance from the Certificates page refuses without it rather than inventing one. |

---

## `config.toml` key map

Only these keys are recognised. A value is applied only when the mapped environment variable is
unset.

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

One further variable exists and is **not** for production use:
`CB_AGENT_TEST_REKEY_INTERVAL_SECONDS` shortens the agent link's Noise rekey interval so the test
suite can exercise a real rekey cycle without waiting out the real interval. Unset, the interval is
byte-for-byte the shipped value. Do not set it on a running deployment.

A key not in this table is ignored, silently. If a setting you changed in `config.toml` had no
effect, check that it is here.

Three of those mappings target variables the **backend process never reads**, so setting them in
`config.toml` changes nothing at runtime. They are documented rather than quietly omitted, because
the mapping exists and an operator will otherwise assume it works:

| TOML key | Maps to | Reality |
|---|---|---|
| `server.host` | `CB_HOST` | Nothing reads `CB_HOST`. The listener address is `HOST`, or the `--host` flag. |
| `server.port` | `CB_PORT` | The backend listener reads `PORT`, or `--port`. `CB_PORT` is a shell-level variable the installers and nginx templates consume — and they run before Python loads `config.toml`, so setting it here is doubly ineffective. |
| `discovery.proxmox_url` | `CB_PROXMOX_URL` | Nothing reads `CB_PROXMOX_URL`. Proxmox endpoints are configured per integration in the database, not by environment. |

---

## Worked examples

### A single-node container behind your own reverse proxy

```bash
# .env next to docker-compose.yml
CB_VAULT_KEY=<44-char Fernet key>
CB_JWT_SECRET=<64 hex chars>
CB_DB_PASSWORD=<random>
NATS_AUTH_TOKEN=<random>

CB_PORT=8080
CB_PORT_HTTPS=8443

# The proxy's own source range — nothing wider.
CB_TRUSTED_PROXY_CIDRS=127.0.0.1/32,::1/128,172.18.0.0/16
CB_WS_REQUIRE_WSS=true

# No forward proxy on this host; record that as a decision.
CB_ALLOW_DIRECT_EGRESS=true
```

Validate before starting:

```bash
docker compose run --rm circuitbreaker python -m app.cli config validate
```

### A native install pointed at an external PostgreSQL

```bash
# /etc/circuitbreaker/.env
CB_DB_URL=postgresql://breaker:<pw>@db.lan:5432/circuitbreaker
CB_DB_POOL_URL=postgresql://breaker:<pw>@db.lan:6432/circuitbreaker
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=5
CB_REDIS_URL=redis://:<pw>@127.0.0.1:6379/0
CB_NATS_URL=nats://127.0.0.1:4222
CB_NATS_TOKEN=<random>
CB_DATA_DIR=/var/lib/circuitbreaker
```

```bash
sudo cb config validate
```

Wiping `CB_DATA_DIR` does **not** reset an external database — users and sessions live there. See
[Configuration Reference](../installation/configuration.md#data-directory-vs-database-full-reset).

### An offline-leaning deployment

```bash
CB_AIRGAP=true            # refuses scans and stops the release check
CB_UPDATE_CHECK=false     # belt and braces; either alone is sufficient
```

Air-gapped *installation* is a separate matter and is
[unsupported for 1.0.0](../release/1.0.0-support-contract.md#deployment-support-matrix): the
artifacts still have to be fetched.

### Tightening the WebSocket caps on a small host

```bash
CB_WS_MAX_CONNECTIONS=20
CB_WS_MAX_PER_IP=3
CB_WS_MON_MAX_CONNECTIONS=40
CB_WS_TELEM_MAX_CONNECTIONS=40
```

A refused connection answers `connection_limit_exceeded` and closes with `1008`. That is the
intended behaviour at the bound — see [Sizing profiles](../operations/sizing-profiles.md).

---

## Related

- [Configuration Reference](../installation/configuration.md) — how to set these per install method
- [Sizing profiles](../operations/sizing-profiles.md) — which bounds to pick for your fleet size
- [cb CLI Tool](../cb-cli.md) — `cb config validate` in each install mode
- [Deployment & Security](../deployment-security.md) — the security reasoning behind the gates
- [Threat model](../security/threat-model.md)
