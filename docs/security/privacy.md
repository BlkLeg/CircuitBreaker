# Privacy

Circuit Breaker is self-hosted. Your inventory, your credentials and your users live in **your**
PostgreSQL database on **your** host. There is no vendor account, no hosted control plane, and no
product analytics.

This page states what data the software holds, exactly what leaves your deployment, and how to stop
each thing that does.

!!! note "\"Telemetry\" here means hardware telemetry"
    [Telemetry](../telemetry.md) in Circuit Breaker is polling *your* servers, UPS units and SNMP
    devices for temperature, fan speed and battery state. It is not usage reporting, and none of it
    is sent anywhere. Nothing in this product reports how you use it.

---

## What the deployment holds

| Data | Contents | Where |
|---|---|---|
| Inventory | Hardware, compute units, services, storage, networks, IP addresses, VLANs, sites, clusters, external nodes, documents, notes and their relationships | PostgreSQL |
| Discovery results | Addresses, open ports, banners, MAC addresses, resolved hostnames, LLDP neighbours, vendor guesses | PostgreSQL |
| Hardware telemetry | Time-series samples from the devices you configured | PostgreSQL |
| Monitor history | Check results, uptime rollups, probe runs, monitor events | PostgreSQL |
| Users | Email, display name, role and scopes, bcrypt password hash, MFA secret and backup codes, avatar, the MD5 Gravatar hash of the email address | PostgreSQL |
| Sessions | Token hash, **IP address**, **user agent**, creation and expiry, revoked flag | PostgreSQL |
| Activity log | Actor, action, entity, old and new value, **IP address**, **user agent**, status code | PostgreSQL |
| Audit log | Actor, action, entity, old and new payload, timestamp, hash chain | PostgreSQL |
| Agents | Device public key, fingerprint, hostname, hashed machine id, OS, architecture, version, primary MAC addresses, reported IP | PostgreSQL |
| Stored credentials | SMTP, Proxmox, SNMP, iDRAC/iLO — Fernet-encrypted with the vault key | PostgreSQL |
| Uploads | Icons, branding assets, document images, avatars | `$CB_DATA_DIR/uploads` |
| Backups | Full-state snapshots — including the vault key **in plaintext** | `$CB_DATA_DIR/backups`, or your configured remote |

Two of these deserve emphasis. **Sessions and the activity log record client IP addresses and user
agents**, which are personal data in most jurisdictions. **Discovery results are a map of your
network**, which is the most sensitive thing in the database even though none of it is a credential.

---

## What leaves your deployment

Complete list. Everything else stays local.

### From the server, by default

| # | Destination | When | What is sent | Turn it off |
|---|---|---|---|---|
| 1 | `api.github.com` | Once at startup, then every 24 h plus up to 30 min of jitter | An unauthenticated `GET` for the public release list, with `User-Agent: circuit-breaker/<version>` and, unavoidably, your egress source IP. **Your running version and source IP are disclosed to GitHub once a day.** Nothing about your inventory, users, network or configuration is sent — the body is empty and the URL carries only `per_page`. | `CB_UPDATE_CHECK=false`, or `CB_AIRGAP=true`, or the `airgap_mode` switch in **Settings**. Any one is enough, and each stops the socket being opened at all. Honours `CB_EGRESS_PROXY_URL`. |

That is the only unprompted outbound request. Everything below happens because of something you
configured or ran.

When `CB_AIRGAP=true` or the database `airgap_mode` switch is enabled, the server's central HTTP
egress gate rejects every public HTTP(S) operation before DNS resolution or socket creation.
Operator-configured monitors and integrations may still reach private or loopback addresses; every
DNS answer must be private/loopback, so unresolved and mixed public/private names are rejected.
SMTP is an explicitly operator-configured, non-HTTP exemption. Air-gap mode governs HTTP(S), not
every possible outbound protocol or requests made directly by a user's browser.

### From the server, when you use the feature

| # | Destination | Trigger | What is sent | Notes |
|---|---|---|---|---|
| 2 | `api.macvendors.com` | A discovery scan, **only** when the offline lookups fail | **The full MAC address** of a device on your network — not just the OUI prefix — in the request path | Offline sources are tried first: the scan-level cache, the curated OUI knowledge base, then the bundled `manuf` database. The API is the last resort. Air-gap mode prevents this by refusing the scan. This client does **not** route through `CB_EGRESS_PROXY_URL`. |
| 3 | `services.nvd.nist.gov` | A CVE feed sync | Paging parameters only. **No inventory data is sent** — the whole feed is downloaded and matched locally. | Bandwidth-heavy; the matching against your inventory happens on your host. |
| 4 | `urlhaus.abuse.ch`, `threatfox.abuse.ch`, `small.oisd.nl` | A threat-feed refresh | Nothing but the request itself; these are host-file downloads. Responses are capped at 5 MB. | |
| 5 | Your OAuth/OIDC provider | Only if you configure OAuth — GitHub, Google or a custom OIDC provider | Whatever the OAuth flow requires: the authorization exchange, and a profile/email read for the signing-in user | One-time `code` and `state` values are scrubbed from access logs before anything is written. |
| 6 | Your SMTP server | Only if you configure SMTP | Invite emails | There is no self-service password reset, so no reset mail is sent. |
| 7 | Let's Encrypt | Only when you request or renew a certificate | The domain name being validated and `CB_TLS_EMAIL` as the ACME account address | See [TLS Certificates](../tls-certificates.md). |
| 8 | `raw.githubusercontent.com` | Only when you run `cb update` on a native install | The installer download | |

### From the browser, not from the server

These are requests the **user's browser** makes while rendering the UI. They are permitted by the
Content-Security-Policy and are visible to the user's own network, not routed through your server.

| Destination | What the browser discloses |
|---|---|
| `www.gravatar.com` / `secure.gravatar.com` | The MD5 hash of a user's email address, when an avatar is rendered from Gravatar |
| `avatars.githubusercontent.com` | GitHub avatar URLs for accounts that signed in with GitHub |
| `fonts.googleapis.com`, `fonts.gstatic.com` | Font requests, with the browser's IP and user agent |
| `api.open-meteo.com`, `geocoding-api.open-meteo.com` | The location the weather widget is configured for |

To eliminate these, tighten the Content-Security-Policy at your reverse proxy — its CSP is the one
the browser applies when you put one in front. Doing so disables the affected UI features; the
directives and the three files that carry them are listed in
[Deployment & Security](../deployment-security.md#content-security-policy).

### From agents

`cb-agent` connects **outbound only** and binds no listening socket. It talks to your Circuit
Breaker server and to the networks its grants authorise — nowhere else. The complete list of
destinations is in [cb-agent § Outbound endpoints](../agent.md#outbound-endpoints).

---

## Retention

Defaults as shipped. The first four are editable in **Settings**.

| Data | Default retention | Where it is set |
|---|---|---|
| Audit log | 90 days | `audit_log_retention_days` |
| Discovery results | 30 days | `discovery_retention_days` |
| Local backup snapshots | 7 snapshots, pruned by age at 30 days | `backup_local_retention_count`, `db_backup_retention_days` |
| Remote/S3 snapshots | 30 snapshots | `backup_s3_retention_count` |
| Monitor probe runs | 7 days | `CB_MONITOR_PROBE_RETENTION_DAYS` |
| NATS event stream | 24 hours | `CB_EVENTS_RETENTION_HOURS` |
| Inventory, telemetry, users, uploads | Until deleted | — |

Setting a retention value to `0` or below disables that purge rather than purging everything —
the sweep logs that it is disabled and skips.

---

## Deleting and exporting

| Operation | How |
|---|---|
| A user deletes their own account | `DELETE /api/v1/auth/me` |
| An administrator deletes a user | `DELETE /api/v1/admin/users/{user_id}`, or **Users** in the UI |
| Revoke a user's sessions | `DELETE /api/v1/admin/users/{user_id}/sessions`; a user can revoke their own with `DELETE /api/v1/users/me/sessions` |
| Export everything | `GET /api/v1/admin/export`, or a full-state snapshot — see [Backup & Restore](../backup-restore.md) |
| Remove the deployment and its data | `cb uninstall` deletes `$CB_DATA_DIR`, which is the database, the uploads and the certificates |

Deleting a user does not rewrite historical audit entries: the audit log is a hash chain, and
editing a row breaks it by design. Plan retention accordingly.

---

## How secrets are kept out of the places you would paste them

| Surface | Protection |
|---|---|
| Application logs | A global redaction filter is installed at import time, before any handler runs |
| Access logs | `code`, `state`, `cb_auth_code`, `cb_mfa_token`, `oauth_token` and `access_token` query parameters are replaced with `[redacted]` before a line is written |
| `cb config validate` output | Secret values are never printed — only the setting name and the tier it came from. Connection strings have their userinfo redacted |
| Error responses | Generic in production. `DEV_MODE=true` returns full stack traces and must never be set on a production instance |
| Snapshot archives | Written mode `0600` — **but they contain the vault key in plaintext.** Treat the file as a credential |

When attaching diagnostics to a bug report, redact `cb doctor` output — it prints connection
targets and environment-derived paths.

---

## Related

- [Threat model](threat-model.md) — what these disclosures mean for an attacker
- [Deployment & Security](../deployment-security.md) — the outbound-egress section in full
- [Configuration precedence and environment catalogue](../reference/configuration-precedence.md) — every switch named above
- [Audit Log](../audit-log.md)
- [Vulnerability disclosure](vulnerability-disclosure.md)
