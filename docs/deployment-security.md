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

For v1.0 release candidates, directly internet-exposed operation is not a supported deployment
boundary unless the release owner records an approved exception. Prefer trusted LAN/VPN access while
SEC-3 and SEC-5 acceptance work is open.

### Core hardening controls

These are the controls Circuit Breaker actually implements. Each one names the setting or role you
can act on.

**Roles and scopes.** Every account carries a role in the hierarchy `viewer < editor < admin`, plus
a read-only `demo` role. Roles map to default scopes: `viewer` and `demo` get `read:*`; `editor`
adds per-entity write scopes (`write:hardware`, `write:services`, `write:networks`, and so on);
`admin` gets `read:* write:* delete:* admin:*`. Give each account the lowest role that works.

**Service accounts for machine access.** Create them with `POST /api/v1/auth/service-account`
rather than sharing a human account or a static token.

**Rate limiting.** Requests are limited per client, keyed by the trusted forwarded identity. It
requires shared Redis storage — the backend refuses to start if rate-limit storage resolves to
in-process memory — and a correct `CB_TRUSTED_PROXY_CIDRS`, or every client behind your proxy shares
one bucket. See [Remote Access](remote-access.md#trusted-proxies).

**Outbound URL / SSRF policy.** Every URL the app is asked to fetch is validated against a policy
chosen for the use case — webhooks, threat feeds, LAN integrations, monitor targets, OIDC, and the
egress proxy each get their own. Literal IPs, resolved DNS answers, and every redirect hop are all
checked, and the cloud metadata address is refused under every policy.

**Scan target ACL.** Discovery targets are checked against the allowed-network ACL, RFC 1918
private-address enforcement, and air-gap mode (`CB_AIRGAP`, or the airgap setting in the UI).

**Audit log hash chain.** Each audit entry stores the SHA-256 of its payload plus the previous
entry's hash, so a deleted or edited row breaks the chain. Repairing a broken chain requires the
explicit `REPAIR_AUDIT_CHAIN` authorization.

**Destructive-action confirmation.** High-impact operations require an `x-cb-confirmation` header
matching the action, an `idempotency-key` of at least 12 characters, and — where a verified backup
is required — `x-cb-backup-verified: true`. Denied attempts are written to the audit log.

**Network boundaries.** Keep the app behind trusted network boundaries and publish only the ports
you need. See [Remote Access](remote-access.md) before exposing it further.

### Native HTTPS

Native Linux installs terminate TLS at nginx. There are no HTTPS "modes" to choose between — the
installer takes one of three paths:

- **Self-signed (default).** If no certificate is already present, the installer generates a
  4096-bit self-signed certificate valid for 10 years with a DNS SAN for the FQDN (or
  `circuitbreaker`) and an IP SAN for the detected server address. Browsers will warn until you
  trust it or replace it.
- **Existing certificate.** If `fullchain.pem` already exists in the TLS directory, it is reused
  untouched. This is how you install a real certificate: place `fullchain.pem` and `privkey.pem`
  there before or after install.
- **Let's Encrypt (`--cert-type letsencrypt --fqdn ... --email ...`).** The installer validates that
  the FQDN resolves to this server's IP and then expects certbot-issued certificates to already be
  at the TLS path. If DNS does not check out, or `--fqdn`/`--email` are missing, it warns and falls
  back to self-signed. `--email` is also written to the environment file as `CB_TLS_EMAIL`, which
  is what the application uses as its ACME account address — so you can obtain and renew a
  certificate from the **Certificates** page afterwards without editing anything. See
  [TLS Certificates](tls-certificates.md).

Certificates live in `${CB_DATA_DIR}/tls` (default `/var/lib/circuitbreaker/tls`), owned by root
and the nginx group (`nginx` or `www-data`), with mode `750` on the directory and `640` on the
`.pem` files.

The **Certificates** page writes to this same directory: activating a certificate replaces
`fullchain.pem` and `privkey.pem` and reloads nginx. That is the only thing that changes what the
server presents — creating or renewing a certificate stores it and nothing more.

Pass `--no-tls` to the installer to skip HTTPS entirely and serve plain HTTP on `CB_PORT`. Only do
this behind another proxy that terminates TLS. Note that HTTP-01 certificate validation is served
from the plain-HTTP listener, so it keeps working in either mode.

Configuration is an environment file at `/etc/circuitbreaker/.env`. There is no `config.yaml`.

### Important environment values

- `CB_VAULT_KEY`: secures sensitive stored credentials. Required — the backend will not start
  without it once encrypted secrets exist.
- `CB_JWT_SECRET`: signs sessions. Must be at least 32 characters, or startup fails. Keep it
  distinct from `CB_VAULT_KEY` — the container entrypoint refuses to start if the two match.
- `CB_TRUSTED_PROXY_CIDRS`: which peers may set `X-Forwarded-*`. See
  [Remote Access](remote-access.md#trusted-proxies).
- `CB_API_TOKEN`: **deprecated and rejected.** Any Bearer token matching it is answered with
  HTTP 401 telling you to migrate to service accounts (`POST /api/v1/auth/service-account`), and
  the backend logs a removal warning at startup if it is set. `CB_LEGACY_AUTH=true` restores the old
  behaviour as a temporary rollback only — do not run with it long-term.

### Outbound egress

Public outbound HTTP can be forced through a forward proxy:

- `CB_EGRESS_PROXY_URL`: the forward proxy to route public outbound requests through. Set this if
  you have one, then set `CB_ALLOW_DIRECT_EGRESS=false`. An invalid value fails startup.
- `CB_ALLOW_DIRECT_EGRESS`: records the decision to run without a proxy. Every shipped template
  defaults it to `true`, because most single-node hosts have no forward proxy; the code default when
  the variable is absent is `false`, so an empty `CB_EGRESS_PROXY_URL` would otherwise abort startup.

`CB_ALLOW_DIRECT_EGRESS=true` waives the proxy requirement **and nothing else**. The outbound URL
policy still applies to every public request — SSRF checks, scheme validation, and redirect
validation are unchanged — and the Redis, NATS, rate-limit-storage, and secret gates still fail
closed.

Do not confuse it with `CB_ALLOW_DEGRADED_DEPENDENCIES`, which is a blanket break-glass flag that
waives *all* of those dependency gates at once. Use that one only to get a broken instance back up
long enough to fix it.

### NATS authentication and TLS

NATS is the internal bus used for discovery, worker dispatch, and notifications. **Token auth is
required in both shipped install paths** — it is not optional and not off by default:

- Docker Compose aborts `docker compose up` if `NATS_AUTH_TOKEN` is unset.
- The native installer generates `CB_NATS_TOKEN` for you and writes it to `/etc/circuitbreaker/.env`.

Authentication options:

- **Token auth:** `CB_NATS_TOKEN` is the preferred variable; `NATS_AUTH_TOKEN` is the fallback the
  client reads if it is unset. Use the same value for the NATS server and for the backend and all
  workers.
- **User/password:** Set `NATS_USER` and `NATS_PASSWORD` for backend and workers. The NATS server must be configured for user auth (e.g. via a custom config file or override command); the client will embed credentials in the connection URL.
- **TLS:** Set `NATS_TLS=true` for backend and workers so they connect with `tls://` and TLS enabled. The NATS server must be configured for TLS (certificates and `--tls` / config); document cert paths and mount them into the server container as needed.

### Content-Security-Policy

The app is served through nginx in both shipped install paths, and nginx sets its own
Content-Security-Policy — that is the one the browser applies. If you put a further reverse proxy in
front, its CSP wins instead. Either way, the CSP in force must allow the same origins as the
backend, or the first-run wizard, map UI, and weather widget break:

- **Gravatar** — `https://www.gravatar.com` (img-src) for profile avatars.
- **Google Fonts** — `https://fonts.googleapis.com` (style-src) and `https://fonts.gstatic.com` (font-src) for the font picker.
- **Open-Meteo** — `https://geocoding-api.open-meteo.com` and `https://api.open-meteo.com` (connect-src) for the weather widget.

Three files carry the directive string and must stay in sync:

- `apps/backend/src/app/middleware/security_headers.py` — the backend's `SecurityHeadersMiddleware`.
- `docker/nginx.mono.conf` — the proxy inside the single-container image.
- `deploy/nginx/circuitbreaker-tls.conf` — the proxy on native installs.

All three also set `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy: strict-origin-when-cross-origin`, HSTS, and a `Permissions-Policy` that denies
camera, microphone, geolocation, payment, USB, and the motion sensors.

---

## 3) Secrets Management & Vault

Circuit Breaker uses a Fernet-based secure vault to encrypt sensitive credentials at rest — entirely local, no third-party key management required.

The vault protects:

- **SMTP credentials** — used for password reset and invite emails.
- **Proxmox API tokens** — the secret half of the PVEAuditor token used during cluster scans.
- **SNMP community strings** and **iDRAC/iLO credentials**.

### Vault key lifecycle

**You do not need to generate the vault key manually.** Both shipped installers create it for you:

- The native installer generates `CB_VAULT_KEY` and writes it to `/etc/circuitbreaker/.env`.
- `install.sh --docker` generates it into the `.env` next to the compose file. Compose itself
  refuses to start without it — `docker-compose.yml` declares `CB_VAULT_KEY` as required.

If no key is present anywhere, the first-run setup wizard generates one and persists it to
`$CB_DATA_DIR/.env`. At startup the backend resolves the key in this order:

1. The `CB_VAULT_KEY` environment variable
2. `$CB_DATA_DIR/.env`
3. A legacy plaintext database column, which is migrated out to `$CB_DATA_DIR/.env` and cleared

Only a hash of the key is ever stored in the database.

**If the vault ends up uninitialized** — after a crash, an accidental data-directory deletion, or a
restore that missed the environment file — put the original key back into `CB_VAULT_KEY` in
`/etc/circuitbreaker/.env` (native) or your compose `.env`, and restart. There is no command that
recovers a lost key; a snapshot from
[Backup & Restore](backup-restore.md#full-restore-disaster-recovery) is the recovery path.

**Vault best practices:**

- Back up the key as soon as the install finishes — store it in a password manager or offline secure
  location, separately from your backups.
- Treat the vault key like a master root credential. Anyone with it can decrypt your stored secrets.
- If you generate a new key instead of restoring the original, existing encrypted secrets (SMTP,
  Proxmox tokens, SNMP strings) become unreadable and must be re-entered in **Settings**.

### What must be persisted

The single-container deployment declares exactly two mounts, and no named volumes at all:

| Mount | Stores |
|---|---|
| `${CB_DATA_DIR:-./circuitbreaker-data}` → `/data` | All persistent state |
| `/run/circuitbreaker` → `/run/circuitbreaker` | The optional `cb-helperd` socket. Not persistence — harmless if the daemon is not installed |

Everything lives under that one `/data` mount. The entrypoint creates these subdirectories inside
it on first start:

| Subdirectory | Stores |
|---|---|
| `pgdata` | PostgreSQL data |
| `uploads` | Uploaded icons, branding assets, and other user files |
| `nats` | NATS/JetStream state |
| `tls` | The `fullchain.pem` / `privkey.pem` nginx serves on `8443` |
| `certs` | Certificate material |
| `redis` | Redis persistence |

The vault key is read from the `CB_VAULT_KEY` environment variable, and persisted to `/data/.env`
when the app has to generate one itself.

Backing up `CB_DATA_DIR` therefore captures everything except the environment file that carries your
secrets — back that up separately, or use the full-state snapshot described in
[Backup & Restore](backup-restore.md).

If you restore the database without the vault key, encrypted secrets such as Proxmox API tokens and
SMTP passwords will no longer be readable.

### Native install persistence

For native Linux installs, the important paths are:

| Path | Stores | Why it matters |
|---|---|---|
| `/var/lib/circuitbreaker` | Default `CB_DATA_DIR`: database, uploads, TLS certs, backups, Redis and NATS state | Core persistent application state |
| `/etc/circuitbreaker/.env` | All generated secrets and runtime environment settings | Without it the vault cannot decrypt anything and the services will not start |
| `${CB_DATA_DIR}/tls` | TLS cert/key files | Required when HTTPS is enabled |
| `/opt/circuitbreaker` | Application files: `bin`, `deploy`, `apps`, and `share/VERSION` | Reinstalled by the installer; nothing user-specific lives here |

Note the paths are unhyphenated — `circuitbreaker`, not `circuit-breaker`. There is no
`config.yaml`; configuration is the `.env` file.

---

## 4) WebSockets (WSS)

Discovery, topology, and status dashboards use WebSockets for live updates. In production you must use **WSS** (WebSocket over HTTPS) so the auth token is not sent in the clear.

- **Use HTTPS:** nginx terminates TLS in both shipped install paths, so connect to `wss://your-host/...` and the WebSocket is tunneled over TLS. Plain `ws://` is only suitable for local development.
- **Cookie-based auth:** When the app is served from the same origin, the session cookie (`cb_session`) is sent automatically with the WebSocket handshake. Prefer this over sending the token as the first message so the token is never visible in client code.
- **Strict WSS only:** Set `CB_WS_REQUIRE_WSS=true` in the backend environment to reject any WebSocket connection that is not considered secure. Use this when the app is exposed and you want to forbid plain-WS access. `X-Forwarded-Proto` is only believed from a trusted peer, so set `CB_TRUSTED_PROXY_CIDRS` correctly first or this will reject every connection — see [Remote Access](remote-access.md#trusted-proxies).

---

## 5) Container isolation (Docker)

The shipped compose file runs one service, `circuitbreaker`, and there are no custom networks to
configure. Isolation is done at the container level instead:

| Control | Setting | Effect |
|---|---|---|
| Read-only root filesystem | `read_only: true` | The image cannot be modified at runtime; only the mounts and tmpfs paths are writable |
| Writable scratch only | `tmpfs` on `/tmp`, `/run`, `/var/log`, `/var/lib/nginx`, `/var/lib/postgresql` | Size-capped and discarded on restart |
| No privilege escalation | `security_opt: no-new-privileges:true` | `setuid` binaries cannot gain privileges |
| Dropped capabilities | `cap_drop: ALL` | Everything is dropped, then a named list is added back |
| Added capabilities | `NET_RAW`, `NET_BIND_SERVICE`, `CHOWN`, `FOWNER`, `SETUID`, `SETGID`, `DAC_OVERRIDE` | SNMP/ICMP polling, binding low ports, the entrypoint's volume-ownership fix, and supervisor dropping privileges for postgres/nginx/nats/redis |
| Resource limits | `deploy.resources.limits` | 2 CPUs and 2 GB memory by default |
| Log rotation | `logging` options | 100 MB × 5 compressed files |

If you narrow these, start with the capability list: `NET_RAW` is only needed if you use SNMP or
ICMP polling, and `NET_BIND_SERVICE` only if `CB_PORT` is below 1024.

The Docker socket is **not** mounted by default. Discovery against the local Docker daemon is an
explicit opt-in overlay (`docker/docker-compose.socket.yml`).

---

## 6) Secret scanning (Gitleaks)

The repo includes a `.gitleaks.toml` allowlist so that Alembic migration revision IDs (hex strings like `b4a9c1d2e8f0` in `down_revision`) are not reported as API keys. Those revision hashes are not secrets — they are version identifiers for the migration chain.

---

## 7) Practical Security Habits

- Rotate tokens on a regular schedule.
- Avoid sharing admin credentials.
- Review audit history for unexpected changes.
- Use least-privilege network access where possible.
- Keep your deployment updated.

---

## 8) Before You Go Live

- Confirm authentication behavior matches your policy.
- Confirm token and secret values are set and persisted.
- Confirm backups can be exported and restored.
- Confirm audit history is visible and reviewed.

---

## Related Guides

- [Settings](settings.md)
- [Backup & Restore](backup-restore.md)
- [Audit Log](audit-log.md)
