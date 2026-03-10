# Deployment & Security

This guide helps you choose the setup style that fits your environment.

- **Lab-friendly setup:** quickest path to get running.
- **Hardened setup:** stronger protection for broader access.

---

## 1) Lab-Friendly Setup (Fast Start)

Best for private, trusted networks and quick testing.

Recommended baseline:

- Keep access limited to trusted network segments.
- Use strong local credentials.
- Keep backups current.

---

## 2) Hardened Setup (Recommended for Shared or Exposed Environments)

Use this profile when more users or broader network access are involved.

### Core hardening checklist

- Require authentication for write actions.
- Use an API token for protected operations.
- Keep the app behind trusted network boundaries.
- Limit external exposure to only required ports.
- Use secure secret values for protected data handling.

### Native HTTPS modes

For Linux native installs, Circuit Breaker supports two HTTPS paths:

- `local` mode: the installer generates a local CA and a server certificate, stores them under `/etc/circuit-breaker/certs`, and can trust the CA locally so browsers stop warning.
- `provided` mode: you point the installer at an existing certificate and private key, and it copies them into the managed cert directory for the service to use directly.

Native HTTPS configuration is written to `/etc/circuit-breaker/config.yaml`, while install-derived runtime paths live in `/etc/circuit-breaker/env`.

### Important environment values

- `CB_API_TOKEN`: protects write operations when configured.
- `CB_VAULT_KEY`: secures sensitive stored credentials.

### NATS authentication and TLS (optional)

NATS is used for discovery, webhooks, and notifications. By default it runs without auth. To enable:

- **Token auth:** Set `NATS_AUTH_TOKEN` in the environment for the **nats** service and for **backend** and all **worker** services (same value). The Compose files pass this through; the NATS server will require the token and the Python client will send it.
- **User/password:** Set `NATS_USER` and `NATS_PASSWORD` for backend and workers. The NATS server must be configured for user auth (e.g. via a custom config file or override command); the client will embed credentials in the connection URL.
- **TLS:** Set `NATS_TLS=true` for backend and workers so they connect with `tls://` and TLS enabled. The NATS server must be configured for TLS (certificates and `--tls` / config); document cert paths and mount them into the server container as needed.

---

## 3) Secrets Management & Vault

Circuit Breaker uses a Fernet-based secure vault to encrypt sensitive credentials at rest — entirely local, no third-party key management required.

The vault protects:

- **SMTP credentials** — used for password reset and invite emails.
- **Proxmox API tokens** — the secret half of the PVEAuditor token used during cluster scans.
- **SNMP community strings** and **iDRAC/iLO credentials**.

### Vault key lifecycle

**You do not need to generate the vault key manually.** During the first-run setup wizard (OOBE), Circuit Breaker automatically generates a cryptographically secure key, writes it to `/app/data/.env` inside the backend data volume, and shows it once so you can back it up.

**If the vault ends up uninitialized** (after a crash, accidental volume deletion, or a headless deploy with no OOBE), use the `cb` CLI to recover:

```bash
cb vault-recover
```

See [cb CLI Tool](cb-cli.md#cb-vault-recover) for details.

**Vault best practices:**

- Back up the key shown during OOBE — store it in a password manager or offline secure location.
- Treat the vault key like a master root credential. Anyone with it can decrypt your stored secrets.
- If you lose the key and cannot recover it, you will need to re-enter all encrypted secrets (SMTP, Proxmox tokens, SNMP strings) in **Settings** after running `cb vault-recover`.

### What must be persisted

For Docker Compose installs, persistence is split across a few mounts:

| Mount | Stores | Why it matters |
|---|---|---|
| `backend-data` → `/app/data` | `app.db`, vault key file, encrypted-secret metadata, uploads runtime data | Required for users, settings, scans, Proxmox config, SMTP config, and vault continuity |
| `../data/uploads/icons` → `/app/data/uploads/icons` | Uploaded icons | Needed only if you use custom icons |
| `../data/uploads/branding` → `/app/data/uploads/branding` | Branding assets | Needed only if you customize logos/backgrounds |
| `caddy_data` | Caddy local CA / ACME state | Prevents HTTPS trust/cert state from being regenerated every restart |
| `caddy_config` | Caddy autosave/config state | Usually low-risk, but keep with `caddy_data` for clean restores |
| `nats_data` | JetStream state | Keeps worker messaging state durable |
| `postgres_data` | PostgreSQL data | Only relevant when using the optional PostgreSQL profile |

If you replace named volumes with host folders, back up these locations together:

1. The backend data directory (`/app/data`)
2. The Caddy data directory
3. Any branding/icon directories you mounted separately

If you restore `app.db` without the vault key file, encrypted secrets such as Proxmox API tokens and SMTP passwords will no longer be readable.

### Native install persistence

For native Linux installs, the important paths are:

| Path | Stores | Why it matters |
|---|---|---|
| `/var/lib/circuit-breaker` | SQLite DB, uploads, runtime data | Core persistent application state |
| `/etc/circuit-breaker/env` | API token and runtime environment overrides | Needed for service configuration continuity |
| `/etc/circuit-breaker/config.yaml` | Native runtime config | Holds host/port/data/TLS settings |
| `/usr/local/share/circuit-breaker` | Frontend bundle, Alembic config, migrations, docs seed, version metadata | Required by packaged native releases |
| `/etc/circuit-breaker/certs` | Native TLS cert/key files | Required when native HTTPS is enabled |

---

## 4) WebSockets (WSS)

Discovery, topology, and status dashboards use WebSockets for live updates. In production you must use **WSS** (WebSocket over HTTPS) so the auth token is not sent in the clear.

- **Use HTTPS:** With Caddy (or another reverse proxy) in front, connect to `wss://your-domain/...` so the WebSocket is tunneled over TLS. Plain `ws://` is only suitable for local development.
- **Cookie-based auth:** When the app is served from the same origin, the session cookie (`cb_session`) is sent automatically with the WebSocket handshake. Prefer this over sending the token as the first message so the token is never visible in client code.
- **Strict WSS only:** Set `CB_WS_REQUIRE_WSS=true` in the backend environment to reject any WebSocket connection that is not considered secure (e.g. when `X-Forwarded-Proto` is not `https`). Use this when the app is exposed and you want to forbid plain-WS access.

---

## 5) Network segmentation (Docker Compose)

The Compose files define segmented networks in addition to the default `cb_net`:

| Network        | Services                                                                 | Purpose |
|----------------|---------------------------------------------------------------------------|---------|
| `cb_frontend`  | Caddy, frontend, cloudflared (tunnel)                                    | Edge and UI; Caddy proxies to frontend and backend. |
| `cb_backend`   | Caddy, backend, postgres, nats                                            | API and data; backend talks only to postgres and nats. |
| `cb_workers`   | discovery worker, webhook-worker, notification-worker, postgres, nats     | Background jobs; workers cannot reach backend or frontend directly. |

All services remain on `cb_net` as well so connectivity is unchanged. Segmentation limits lateral movement: a compromised worker can reach only postgres and NATS, not the backend API or frontend.

---

## 6) Practical Security Habits

- Rotate tokens on a regular schedule.
- Avoid sharing admin credentials.
- Review audit history for unexpected changes.
- Use least-privilege network access where possible.
- Keep your deployment updated.

---

## 7) Before You Go Live

- Confirm authentication behavior matches your policy.
- Confirm token and secret values are set and persisted.
- Confirm backups can be exported and restored.
- Confirm audit history is visible and reviewed.

---

## Related Guides

- [Settings](settings.md)
- [Backup & Restore](backup-restore.md)
- [Audit Log](audit-log.md)
