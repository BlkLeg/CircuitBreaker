# API Reference

This page documents the control-plane HTTP API that the web UI, the `cb` CLI and `cb-agent`
speak to. Every path below is derived from the FastAPI application in
`apps/backend/src/app/`; nothing here is aspirational.

!!! warning "`/api/v1` is not a stable public API in 1.0.0"
    The [1.0.0 compatibility policy](../release/1.0.0-compatibility-policy.md#api-and-client-compatibility)
    classifies a third-party client that depends on undocumented `/api/v1` behaviour as
    **degraded/unsupported**, and the [support contract](../release/1.0.0-support-contract.md#feature-scope)
    lists "Public API/SDK" as **deferred**. The surface exists for the product's own UI and CLI.
    Paths, payloads and status codes may change inside the 1.0 line. Build against it if you
    self-host it; do not build a product on it.

---

## Base URL and schema

| Thing | Value |
|---|---|
| Route prefix | `/api/v1` (`API_PREFIX`, changing it is untested) |
| OpenAPI schema | `GET /api/openapi.json` |
| Swagger UI | `GET /api/docs` |
| ReDoc | `GET /api/redoc` |
| Reported version | `settings.app_version` — the `VERSION` file, or `APP_VERSION` when set |

The schema served at `/api/openapi.json` is the authoritative machine-readable contract; the
tables at the bottom of this page are that schema rendered for reading. To regenerate them, see
[Keeping this page honest](#keeping-this-page-honest).

---

## Authentication

Three credential types reach the same resolver
(`app/core/security.py:resolve_optional_user_id_sync`). All of them end in a user id; there is no
separate "API user" concept.

| Credential | How it is presented | Notes |
|---|---|---|
| Session cookie | `Cookie: cb_session=<jwt>` | `HttpOnly`, `SameSite=Strict`, `Secure` whenever the request is TLS or arrives via a trusted proxy asserting `X-Forwarded-Proto: https`. Set by the login endpoints. Lifetime is the configured session timeout, default 24 h. |
| Bearer JWT | `Authorization: Bearer <jwt>` | The same token value as the cookie. Session JWTs carry the audience `fastapi-users:auth`, so a password-reset or MFA token cannot be replayed as a session. |
| API token / service account | `Authorization: Bearer <token>` | Created by `POST /api/v1/auth/api-token` or `POST /api/v1/auth/service-account`. Stored as a per-token salted HMAC-SHA256 (`{salt_hex}:{hmac_hex}`), never in clear. Supports expiry, rotation and revocation. |

`CB_API_TOKEN` is **deprecated and rejected**: a request presenting it is answered `401` unless
`CB_LEGACY_AUTH=true` restores the old grant as a temporary rollback. Use a service account.

### Roles and scopes

Roles form the hierarchy `viewer < editor < admin`, plus a read-only `demo` role
(`app/core/rbac.py`). Each role has a default scope set:

| Role | Default scopes |
|---|---|
| `viewer`, `demo` | `read:*` |
| `editor` | `read:*` plus `write:hardware`, `write:services`, `write:networks`, `write:clusters`, `write:external`, `write:compute`, `write:storage`, `write:misc`, `write:docs`, `write:graph`, `write:layout` |
| `admin` | `read:*`, `write:*`, `delete:*`, `admin:*` |

A token may be granted a narrower set. The grantable scopes — served to clients by
`GET /api/v1/auth/scopes` — are `read:*`, `write:*`, `delete:*`, `admin:*`, `write:telemetry`
and `*:*`.

### CSRF

`CSRFMiddleware` enforces a double-submit check on `POST`, `PUT`, `PATCH` and `DELETE` **when the
request carries a `cb_session` cookie**. Send the value of the readable `cb_csrf` cookie back in
`X-CSRF-Token`. Requests authenticated by `Authorization: Bearer` alone carry no session cookie
and are therefore not subject to the check — which is what makes headless clients simple. The
session-establishing endpoints (`/auth/login`, `/auth/register`, `/auth/demo`, `/auth/accept-invite`,
`/auth/vault-reset`, `/auth/force-change-password`, `/auth/mfa/verify`) and `/api/v1/health` are
exempt by prefix.

### Before first-run completes

While the deployment is unbootstrapped (`auth_enabled` is false), an admin-equivalent sentinel is
granted **only** to the first-run surface: everything under `/api/v1/bootstrap` and `/api/v1/auth`,
`GET`/`HEAD` on `/api/v1/settings`, and `PATCH /api/v1/settings/oauth`. Every other route answers
`401` until an administrator exists. Creating that first administrator additionally requires the
setup token — see [Configuration](../installation/configuration.md#first-admin-setup-token).

---

## Error contract

Application errors return a JSON body with a machine-readable code
(`app/schemas/errors.py`, `app/main.py`):

```json
{ "error_code": "RESOURCE_NOT_FOUND", "detail": "Hardware 42 not found" }
```

| Field | When present |
|---|---|
| `error_code` | Errors raised as `AppError` and every unhandled 500 |
| `detail` | Always. For a `422` it is the FastAPI validation-error list, not a string |
| `fields` | Field-level validation errors, where the endpoint supplies them |
| `retry_after` | `429` only |

The codes defined today are `INTERNAL_SERVER_ERROR`, `VALIDATION_ERROR`, `RESOURCE_NOT_FOUND`,
`RATE_LIMITED` and `PERMISSION_DENIED`.

A `422` additionally carries `body`: the first 500 characters of the offending request body.
Unhandled exceptions return `{"error_code": "INTERNAL_SERVER_ERROR", "detail": "Internal server
error"}` — with a `traceback` field **only** when `DEV_MODE=true`, which must never be set in
production.

### Deliberately gone

| Path | Status | Why |
|---|---|---|
| `/api/v1/tenants` and `/api/v1/tenants/{any}` (all methods) | `410 Gone` | 1.0 is single-tenant by decision — [ADR-0003](../adr/0003-defer-true-multi-tenancy.md). The route stays mounted so a stale client gets an explicit answer rather than reawakening dormant tenant behaviour. |
| `POST /api/v1/auth/forgot-password`, `POST /api/v1/auth/reset-password` | `410 Gone` | There is no self-service password reset. Recovery is administrator-mediated (**Users → Reset Password**), or **Reset With Vault Key** for the case where no administrator can sign in. |

---

## Rate limits

Two independent mechanisms exist.

**Per-route limits (`slowapi`)** apply to the sensitive categories and are keyed by the trusted
client identity — the forwarded chain only when the socket peer is inside
`CB_TRUSTED_PROXY_CIDRS`, otherwise the socket peer itself. The active profile is
`rate_limit_profile` in settings:

| Category | `relaxed` | `normal` (default) | `strict` |
|---|---|---|---|
| `auth` | 20/minute | 5/minute | 3/minute |
| `ip_check` | 30/minute | 10/minute | 5/minute |
| `mfa_verify` | 10/15 minutes | 5/15 minutes | 3/15 minutes |
| `scan` | 5/minute | 1/minute | 1/5 minutes |
| `telemetry` | 30/minute | 15/minute | 5/minute |
| `default` | 60/minute | 30/minute | 10/minute |

Rate-limit storage **must** be shared Redis; the backend refuses to start when it resolves to
in-process memory. Getting `CB_TRUSTED_PROXY_CIDRS` wrong collapses every client behind your proxy
onto one bucket — see [Remote Access](../remote-access.md#trusted-proxies).

**`TenantRateLimitMiddleware`** is a Redis sliding window of `CB_RATE_LIMIT_RPM` (default 600)
requests per 60 s keyed by tenant. Because 1.0 sets no tenant context, it is inert on the normal
path; it is retained as a compatibility shim. Health and metrics paths are skipped by name so a
Redis outage can never turn `/livez` into a `503` restart storm.

---

## Destructive-action confirmation

High-impact operations require three request headers (`app/core/destructive_actions.py`):

| Header | Value |
|---|---|
| `x-cb-confirmation` | The action name being confirmed |
| `idempotency-key` | At least 12 characters |
| `x-cb-backup-verified` | `true` — only where the action requires a verified backup |

Denied attempts are written to the audit log.

---

## Health and readiness

These four are the SRV-03 probe contract. `GET` and `HEAD` are both accepted.

| Path | Meaning |
|---|---|
| `/api/v1/livez` | Liveness. Touches no dependency and takes no lock; `200` whenever the event loop runs, including through a database or Redis outage. **This is the only probe a restart decision should turn on.** |
| `/api/v1/startupz` | Startup. `503` with `started: false` until initialisation completes, `200` after — including while stopping, so a slow migration is not mistaken for a dead process. |
| `/api/v1/readyz` | Readiness. `200` with `ready: true` when the lifecycle state is ready and every dependency probe answers `ok`; `503` otherwise, including `state: "stopping"` during drain. The body also carries `health` (the derived health state — the only place a *degraded* server is distinguishable from a not-ready one), `degraded` (which optional dependencies are down), and `writes_permitted` — which is not advice, but what the write-admission guard is enforcing on this process right now. |
| `/api/v1/health` | Legacy shape, kept for the frontend poll and the installer's readiness wait. New consumers should use the three above. |

`/api/v1/health` returns the instance `version` **only to an authenticated caller** — the version
is deliberately withheld from anonymous callers as fingerprinting material.

### Writes are refused when they cannot be served safely

Readiness is enforced, not merely advertised. A mutating request (`POST`, `PUT`, `PATCH`, `DELETE`)
to anything under `/api/` is admitted only while the health state says a write can be persisted:

| Condition | Response |
|---|---|
| A required dependency cannot answer — PostgreSQL unreachable, or a schema that does not match this build | `503` with `error_code: SERVICE_NOT_READY` |
| The process is starting or draining | `503` with `error_code: SERVER_DRAINING` while stopping |

Both carry `Retry-After: 5` and a `health` field naming the state. Reads, WebSocket sessions and the
four health endpoints above are deliberately **not** guarded — an established agent link is drained
by the lifespan rather than refused mid-frame, and health and diagnostics stay reachable in every
state, which is exactly when an operator needs them.

The lifecycle half of the guard only fires in a process whose ASGI lifespan actually drives the
state, so an embedded or test host that mounts the app without a lifespan is not permanently closed.

---

## Prometheus metrics

`GET /api/v1/metrics/metrics` returns the Prometheus text exposition format. It requires
authentication (`401` otherwise) and is excluded from the OpenAPI schema, so it does not appear in
the catalogue below. Contents and stability caveats: [Metrics](../metrics.md).

---

## WebSocket endpoints

WebSocket routes carry no OpenAPI entry, so they are listed here explicitly.

| Path | Auth | Purpose |
|---|---|---|
| `/api/v1/agents/enroll` | **None** — the Noise IK handshake *is* the authentication | Agent enrollment: handshake, `hello`, then hold open polling for the approval decision. Rate-gated per IP and globally before the first handshake byte is read. |
| `/api/v1/agents/link` | **None** — Noise IK handshake | The live agent link: heartbeats, telemetry, discovery results, probe dispatch, capability and update control frames. |
| `/api/v1/agents/stream` | Session | Agent presence fan-out to the UI. |
| `/api/v1/discovery/stream` | Session | Discovery job progress and results. |
| `/api/v1/telemetry/stream` | Session | Live hardware telemetry. |
| `/api/v1/monitors/stream` | Session | Monitor state changes and check results. |
| `/api/v1/topology/stream` | Session | Topology graph updates. |

Session-authenticated sockets take the token from the `cb_session` cookie in the handshake, or —
`/monitors`, `/telemetry` and `/agents/stream` only — from a first text frame within 10 seconds.
Prefer the cookie: a token sent as a frame is visible to client code.

Close codes used: `1008` for unauthorized, `wss_required`, `auth_timeout`, `ip_not_allowed`,
`clock_skew` and malformed input; `1013` for rate limiting and the concurrent-pending-enrollment
cap; `1011` for an unexpected server error; `1000` for a clean, deliberate close.

When `CB_WS_REQUIRE_WSS=true`, a handshake that is not `wss://` — and not asserted as HTTPS by a
peer inside `CB_TRUSTED_PROXY_CIDRS` — is refused. Connection caps are per-endpoint; see the
[sizing profiles](../operations/sizing-profiles.md#websocket-connection-caps).

Two HTTP endpoints report socket state rather than opening one:
`GET /api/v1/discovery/ws/status` and `GET /api/v1/topology/ws/status`.

---

## Static and unlisted routes

Excluded from the OpenAPI schema on purpose:

| Path | Serves |
|---|---|
| `/uploads`, `/user-icons`, `/branding` | Uploaded files and branding assets from the data directory |
| `/assets`, `/icons` | Built frontend assets, when a frontend is bundled |
| `/favicon.ico` | Favicon, branding-aware |
| `/install-agent.sh` | The agent installer script `cb-agent` bootstraps from |
| `/` | The single-page app, when a frontend is bundled |

The API and workers start without the bundled frontend; these mounts are skipped when the static
directory is absent.

---

## Endpoint catalogue

Grouped by OpenAPI tag. Path parameters are shown in the FastAPI form. An operation appearing here
is not a promise that it is stable — see the banner at the top of this page.

Health probes carry no tag in the schema and are grouped under `health` below; each also accepts
`HEAD`, registered separately and left out of the schema so the four probes do not publish duplicate
operation ids — which is a generation error in every OpenAPI client generator. The twelve operations
under `tenants` and the two password-reset operations under `auth` are the
[deliberately gone](#deliberately-gone) routes: they exist so a stale client receives `410 Gone`
rather than silence.

### `admin` — 4 operations

| Method | Path | Operation |
|---|---|---|
| `POST` | `/api/v1/admin/clear-lab` | Clear Lab |
| `GET` | `/api/v1/admin/export` | Export Backup |
| `POST` | `/api/v1/admin/import` | Import Backup |
| `GET` | `/api/v1/admin/recent-changes` | Recent Changes |

### `admin-audit` — 2 operations

| Method | Path | Operation |
|---|---|---|
| `POST` | `/api/v1/admin/audit-log/repair-chain` | Audit Log Repair Chain |
| `GET` | `/api/v1/admin/audit-log/verify-chain` | Audit Log Verify Chain |

### `admin-db` — 7 operations

| Method | Path | Operation |
|---|---|---|
| `POST` | `/api/v1/admin/db/backup` | Trigger Backup |
| `GET` | `/api/v1/admin/db/health` | Db Health |
| `POST` | `/api/v1/admin/db/snapshot` | Trigger Snapshot |
| `GET` | `/api/v1/admin/db/snapshots` | List Snapshots |
| `GET` | `/api/v1/admin/settings/backup` | Get Backup Settings |
| `PUT` | `/api/v1/admin/settings/backup` | Update Backup Settings |
| `POST` | `/api/v1/admin/settings/backup/test` | Test Backup Connection |

### `admin-users` — 13 operations

| Method | Path | Operation |
|---|---|---|
| `GET` | `/api/v1/admin/invites` | List Invites |
| `POST` | `/api/v1/admin/invites` | Create Invite Endpoint |
| `PATCH` | `/api/v1/admin/invites/{invite_id}` | Update Invite |
| `GET` | `/api/v1/admin/user-actions/{user_id}` | Get User Actions |
| `GET` | `/api/v1/admin/users` | List Users |
| `POST` | `/api/v1/admin/users` | Create User |
| `POST` | `/api/v1/admin/users/local` | Create Local User |
| `DELETE` | `/api/v1/admin/users/{user_id}` | Delete User |
| `PATCH` | `/api/v1/admin/users/{user_id}` | Update User |
| `POST` | `/api/v1/admin/users/{user_id}/masquerade` | Masquerade User |
| `POST` | `/api/v1/admin/users/{user_id}/reset-password` | Reset User Password |
| `DELETE` | `/api/v1/admin/users/{user_id}/sessions` | Revoke User Sessions |
| `POST` | `/api/v1/admin/users/{user_id}/unlock` | Unlock User Endpoint |

### `agents` — 26 operations

| Method | Path | Operation |
|---|---|---|
| `GET` | `/api/v1/agents` | Get Agents |
| `GET` | `/api/v1/agents/capability-defaults` | Get Capability Defaults |
| `GET` | `/api/v1/agents/install-command` | Get Install Command |
| `GET` | `/api/v1/agents/metrics/series` | Get Agents Metrics Series |
| `POST` | `/api/v1/agents/pairing/lookup` | Post Pairing Lookup |
| `GET` | `/api/v1/agents/pending` | Get Pending Agents |
| `GET` | `/api/v1/agents/presence` | Get Agents Presence |
| `GET` | `/api/v1/agents/probe-eligible` | Get Probe Eligible Agents |
| `GET` | `/api/v1/agents/server-key/pending` | Get Server Key Pending Agents |
| `POST` | `/api/v1/agents/server-key/rotate` | Post Server Key Rotate |
| `GET` | `/api/v1/agents/server-key/status` | Get Server Key Rotation Status |
| `DELETE` | `/api/v1/agents/{agent_id}` | Delete Agent |
| `GET` | `/api/v1/agents/{agent_id}` | Get Agent Detail |
| `PATCH` | `/api/v1/agents/{agent_id}` | Patch Agent |
| `POST` | `/api/v1/agents/{agent_id}/approve` | Post Approve |
| `PUT` | `/api/v1/agents/{agent_id}/capabilities` | Put Capabilities |
| `GET` | `/api/v1/agents/{agent_id}/discovery` | Get Agent Discovery |
| `POST` | `/api/v1/agents/{agent_id}/discovery/pause` | Pause Agent Discovery |
| `POST` | `/api/v1/agents/{agent_id}/discovery/resume` | Resume Agent Discovery |
| `GET` | `/api/v1/agents/{agent_id}/events` | Get Agent Events |
| `GET` | `/api/v1/agents/{agent_id}/probes` | Get Agent Probes |
| `POST` | `/api/v1/agents/{agent_id}/reject` | Post Reject |
| `POST` | `/api/v1/agents/{agent_id}/revoke` | Post Revoke |
| `GET` | `/api/v1/agents/{agent_id}/telemetry` | Get Agent Telemetry |
| `GET` | `/api/v1/agents/{agent_id}/telemetry/history` | Get Agent Telemetry History |
| `POST` | `/api/v1/agents/{agent_id}/update` | Post Update |

### `agents-binary` — 1 operations

| Method | Path | Operation |
|---|---|---|
| `GET` | `/api/v1/agents/binary/{version}/{os_name}/{arch}` | Get Binary |

### `assets` — 2 operations

| Method | Path | Operation |
|---|---|---|
| `POST` | `/api/v1/assets/branding/favicon` | Upload Favicon |
| `POST` | `/api/v1/assets/user-icon` | Upload User Icon |

### `auth` — 25 operations

| Method | Path | Operation |
|---|---|---|
| `POST` | `/api/v1/auth/accept-invite` | Accept Invite Endpoint |
| `POST` | `/api/v1/auth/api-token` | Create Api Token |
| `GET` | `/api/v1/auth/api-tokens` | List Api Tokens |
| `DELETE` | `/api/v1/auth/api-tokens/{token_id}` | Revoke Api Token |
| `POST` | `/api/v1/auth/api-tokens/{token_id}/rotate` | Rotate Api Token |
| `POST` | `/api/v1/auth/demo` | Create Demo Session |
| `POST` | `/api/v1/auth/force-change-password` | Force Change Password |
| `POST` | `/api/v1/auth/forgot-password` | Forgot Password |
| `POST` | `/api/v1/auth/jwt/login` | Auth:Jwt.Login |
| `POST` | `/api/v1/auth/jwt/logout` | Auth:Jwt.Logout |
| `POST` | `/api/v1/auth/login` | Login Compat |
| `POST` | `/api/v1/auth/logout` | Logout |
| `DELETE` | `/api/v1/auth/me` | Delete Me |
| `GET` | `/api/v1/auth/me` | Get Me Compat |
| `PUT` | `/api/v1/auth/me/avatar` | Upload Avatar |
| `POST` | `/api/v1/auth/mfa/activate` | Mfa Activate |
| `POST` | `/api/v1/auth/mfa/backup-codes/regenerate` | Mfa Regenerate Backup Codes |
| `POST` | `/api/v1/auth/mfa/disable` | Mfa Disable |
| `POST` | `/api/v1/auth/mfa/setup` | Mfa Setup |
| `POST` | `/api/v1/auth/mfa/verify` | Mfa Verify |
| `POST` | `/api/v1/auth/register` | Register User |
| `POST` | `/api/v1/auth/reset-password` | Reset Password |
| `GET` | `/api/v1/auth/scopes` | List Grantable Scopes |
| `POST` | `/api/v1/auth/service-account` | Create Service Account |
| `POST` | `/api/v1/auth/vault-reset` | Vault Reset Password |

### `bootstrap` — 6 operations

| Method | Path | Operation |
|---|---|---|
| `POST` | `/api/v1/bootstrap/domain` | Configure Bootstrap Domain |
| `POST` | `/api/v1/bootstrap/initialize` | Initialize Bootstrap |
| `POST` | `/api/v1/bootstrap/initialize-oauth` | Initialize Bootstrap Oauth |
| `GET` | `/api/v1/bootstrap/onboarding` | Get Onboarding Step |
| `PATCH` | `/api/v1/bootstrap/onboarding` | Set Onboarding Step |
| `GET` | `/api/v1/bootstrap/status` | Get Bootstrap Status |

### `branding` — 6 operations

| Method | Path | Operation |
|---|---|---|
| `GET` | `/api/v1/branding/export` | Export Theme |
| `POST` | `/api/v1/branding/import` | Import Theme |
| `GET` | `/api/v1/branding/manifest.json` | Dynamic Manifest |
| `POST` | `/api/v1/branding/upload-login-bg` | Upload Login Bg |
| `POST` | `/api/v1/branding/upload-login-logo` | Upload Login Logo |
| `DELETE` | `/api/v1/branding/{asset_type}` | Delete Branding Asset |

### `capabilities` — 1 operations

| Method | Path | Operation |
|---|---|---|
| `GET` | `/api/v1/capabilities` | Get Capabilities |

### `catalog` — 3 operations

| Method | Path | Operation |
|---|---|---|
| `GET` | `/api/v1/catalog/search` | Search Catalog |
| `GET` | `/api/v1/catalog/vendors` | List Vendors |
| `GET` | `/api/v1/catalog/vendors/{vendor_key}/devices` | List Devices |

### `categories` — 4 operations

| Method | Path | Operation |
|---|---|---|
| `GET` | `/api/v1/categories` | Get Categories |
| `POST` | `/api/v1/categories` | Post Category |
| `DELETE` | `/api/v1/categories/{category_id}` | Del Category |
| `PATCH` | `/api/v1/categories/{category_id}` | Patch Category |

### `certificates` — 7 operations

| Method | Path | Operation |
|---|---|---|
| `GET` | `/api/v1/certificates` | List Certificates |
| `POST` | `/api/v1/certificates` | Create Certificate |
| `DELETE` | `/api/v1/certificates/{cert_id}` | Delete Certificate |
| `GET` | `/api/v1/certificates/{cert_id}` | Get Certificate |
| `PUT` | `/api/v1/certificates/{cert_id}` | Update Certificate |
| `POST` | `/api/v1/certificates/{cert_id}/activate` | Activate Certificate Route |
| `POST` | `/api/v1/certificates/{cert_id}/renew` | Renew Certificate |

### `clusters` — 9 operations

| Method | Path | Operation |
|---|---|---|
| `GET` | `/api/v1/hardware-clusters` | List Clusters |
| `POST` | `/api/v1/hardware-clusters` | Create Cluster |
| `DELETE` | `/api/v1/hardware-clusters/{cluster_id}` | Delete Cluster |
| `GET` | `/api/v1/hardware-clusters/{cluster_id}` | Get Cluster |
| `PATCH` | `/api/v1/hardware-clusters/{cluster_id}` | Update Cluster |
| `GET` | `/api/v1/hardware-clusters/{cluster_id}/members` | List Members |
| `POST` | `/api/v1/hardware-clusters/{cluster_id}/members` | Add Member |
| `DELETE` | `/api/v1/hardware-clusters/{cluster_id}/members/{member_id}` | Remove Member |
| `PATCH` | `/api/v1/hardware-clusters/{cluster_id}/members/{member_id}` | Update Member |

### `compute-units` — 9 operations

| Method | Path | Operation |
|---|---|---|
| `GET` | `/api/v1/compute-units` | List Compute Units |
| `POST` | `/api/v1/compute-units` | Create Compute Unit |
| `GET` | `/api/v1/compute-units/icons` | List Icons |
| `POST` | `/api/v1/compute-units/icons/upload` | Upload Icon |
| `DELETE` | `/api/v1/compute-units/icons/{slug}` | Delete Icon |
| `DELETE` | `/api/v1/compute-units/{cu_id}` | Delete Compute Unit |
| `GET` | `/api/v1/compute-units/{cu_id}` | Get Compute Unit |
| `PATCH` | `/api/v1/compute-units/{cu_id}` | Patch Compute Unit |
| `GET` | `/api/v1/compute-units/{cu_id}/networks` | List Compute Networks |

### `cve` — 4 operations

| Method | Path | Operation |
|---|---|---|
| `GET` | `/api/v1/cve/entity/{entity_type}/{entity_id}` | Cves For Entity |
| `GET` | `/api/v1/cve/search` | Search Cves |
| `GET` | `/api/v1/cve/status` | Cve Status |
| `POST` | `/api/v1/cve/sync` | Trigger Sync |

### `discovery` — 37 operations

| Method | Path | Operation |
|---|---|---|
| `GET` | `/api/v1/discovery/docker/networks` | Docker Networks |
| `GET` | `/api/v1/discovery/docker/status` | Docker Status |
| `POST` | `/api/v1/discovery/docker/sync` | Docker Sync |
| `GET` | `/api/v1/discovery/eligible-agents` | Get Eligible Discovery Agents |
| `GET` | `/api/v1/discovery/jobs` | List Jobs |
| `DELETE` | `/api/v1/discovery/jobs/{job_id}` | Cancel Job |
| `GET` | `/api/v1/discovery/jobs/{job_id}` | Get Job |
| `POST` | `/api/v1/discovery/jobs/{job_id}/batch-import` | Batch Import Results |
| `POST` | `/api/v1/discovery/jobs/{job_id}/enrich` | Enrich Opnsense Job |
| `POST` | `/api/v1/discovery/jobs/{job_id}/import-as-network` | Import As Network Endpoint |
| `GET` | `/api/v1/discovery/jobs/{job_id}/logs` | Get Job Logs |
| `GET` | `/api/v1/discovery/jobs/{job_id}/results` | Get Job Results |
| `GET` | `/api/v1/discovery/listener/events` | Get Listener Events |
| `GET` | `/api/v1/discovery/listener/status` | Get Listener Status |
| `POST` | `/api/v1/discovery/lldp-enrich` | Lldp Enrich |
| `POST` | `/api/v1/discovery/lldp-jobs/{job_id}/apply` | Lldp Apply |
| `GET` | `/api/v1/discovery/lldp-jobs/{job_id}/results` | Lldp Job Results |
| `POST` | `/api/v1/discovery/pause` | Pause Agent Discovery Globally |
| `GET` | `/api/v1/discovery/profiles` | Get Profiles |
| `POST` | `/api/v1/discovery/profiles` | Create Profile |
| `DELETE` | `/api/v1/discovery/profiles/{profile_id}` | Delete Profile |
| `PATCH` | `/api/v1/discovery/profiles/{profile_id}` | Update Profile |
| `POST` | `/api/v1/discovery/profiles/{profile_id}/pause` | Pause Profile |
| `POST` | `/api/v1/discovery/profiles/{profile_id}/resume` | Resume Profile |
| `POST` | `/api/v1/discovery/profiles/{profile_id}/run` | Run Profile Scan |
| `GET` | `/api/v1/discovery/proxmox-runs` | List Proxmox Runs |
| `GET` | `/api/v1/discovery/proxmox-runs/{run_id}` | Get Proxmox Run |
| `GET` | `/api/v1/discovery/readiness` | Get Readiness |
| `GET` | `/api/v1/discovery/results` | List Results |
| `POST` | `/api/v1/discovery/results/bulk-merge` | Bulk Merge |
| `POST` | `/api/v1/discovery/results/enhanced-bulk-merge` | Enhanced Bulk Merge |
| `POST` | `/api/v1/discovery/results/suggest` | Suggest Actions |
| `POST` | `/api/v1/discovery/results/{result_id}/merge` | Merge Result |
| `POST` | `/api/v1/discovery/resume` | Resume Agent Discovery Globally |
| `POST` | `/api/v1/discovery/scan` | Run Adhoc Scan |
| `GET` | `/api/v1/discovery/status` | Get Discovery Status |
| `GET` | `/api/v1/discovery/vendor-catalog` | Vendor Catalog |

### `discovery-ws` — 1 operations

| Method | Path | Operation |
|---|---|---|
| `GET` | `/api/v1/discovery/ws/status` | Ws Status |

### `docs` — 12 operations

| Method | Path | Operation |
|---|---|---|
| `GET` | `/api/v1/docs` | List Docs |
| `POST` | `/api/v1/docs` | Create Doc |
| `DELETE` | `/api/v1/docs/attach` | Detach Doc |
| `POST` | `/api/v1/docs/attach` | Attach Doc |
| `GET` | `/api/v1/docs/by-entity` | Docs By Entity |
| `GET` | `/api/v1/docs/export` | Export Docs |
| `POST` | `/api/v1/docs/import` | Import Docs |
| `DELETE` | `/api/v1/docs/{doc_id}` | Delete Doc |
| `GET` | `/api/v1/docs/{doc_id}` | Get Doc |
| `PATCH` | `/api/v1/docs/{doc_id}` | Patch Doc |
| `GET` | `/api/v1/docs/{doc_id}/entities` | Doc Entities |
| `POST` | `/api/v1/docs/{doc_id}/upload-image` | Upload Doc Image |

### `environments` — 4 operations

| Method | Path | Operation |
|---|---|---|
| `GET` | `/api/v1/environments` | Get Environments |
| `POST` | `/api/v1/environments` | Post Environment |
| `DELETE` | `/api/v1/environments/{environment_id}` | Del Environment |
| `PATCH` | `/api/v1/environments/{environment_id}` | Patch Environment |

### `events` — 2 operations

| Method | Path | Operation |
|---|---|---|
| `GET` | `/api/v1/events/status` | Events Status |
| `GET` | `/api/v1/events/stream` | Events Stream |

### `external-nodes` — 9 operations

| Method | Path | Operation |
|---|---|---|
| `DELETE` | `/api/v1/external-node-networks/{relation_id}` | Unlink Network |
| `GET` | `/api/v1/external-nodes` | List External Nodes |
| `POST` | `/api/v1/external-nodes` | Create External Node |
| `DELETE` | `/api/v1/external-nodes/{node_id}` | Delete External Node |
| `GET` | `/api/v1/external-nodes/{node_id}` | Get External Node |
| `PATCH` | `/api/v1/external-nodes/{node_id}` | Patch External Node |
| `GET` | `/api/v1/external-nodes/{node_id}/networks` | List Networks |
| `POST` | `/api/v1/external-nodes/{node_id}/networks` | Link Network |
| `GET` | `/api/v1/external-nodes/{node_id}/services` | List Services |

### `graph` — 6 operations

| Method | Path | Operation |
|---|---|---|
| `DELETE` | `/api/v1/graph/edges/{edge_id}` | Delete Edge |
| `PATCH` | `/api/v1/graph/edges/{edge_id}` | Update Edge Type |
| `GET` | `/api/v1/graph/layout` | Get Layout |
| `POST` | `/api/v1/graph/layout` | Save Layout |
| `POST` | `/api/v1/graph/place-node` | Place Node |
| `GET` | `/api/v1/graph/topology` | Get Topology |

### `hardware` — 10 operations

| Method | Path | Operation |
|---|---|---|
| `GET` | `/api/v1/hardware` | List Hardware |
| `POST` | `/api/v1/hardware` | Create Hardware |
| `DELETE` | `/api/v1/hardware-connections/{connection_id}` | Delete Hardware Connection |
| `DELETE` | `/api/v1/hardware/{hardware_id}` | Delete Hardware |
| `GET` | `/api/v1/hardware/{hardware_id}` | Get Hardware |
| `PATCH` | `/api/v1/hardware/{hardware_id}` | Patch Hardware |
| `PUT` | `/api/v1/hardware/{hardware_id}` | Replace Hardware |
| `GET` | `/api/v1/hardware/{hardware_id}/clusters` | Get Clusters For Hardware |
| `POST` | `/api/v1/hardware/{hardware_id}/connections` | Create Hardware Connection |
| `GET` | `/api/v1/hardware/{hardware_id}/network-memberships` | Get Network Memberships |

### `health` — 4 operations

| Method | Path | Operation |
|---|---|---|
| `GET` | `/api/v1/health` | Health |
| `GET` | `/api/v1/livez` | Livez |
| `GET` | `/api/v1/readyz` | Readyz |
| `GET` | `/api/v1/startupz` | Startupz |

### `integrations` — 19 operations

| Method | Path | Operation |
|---|---|---|
| `GET` | `/api/v1/integrations` | List Integrations |
| `POST` | `/api/v1/integrations` | Create Integration |
| `GET` | `/api/v1/integrations/monitors` | List All Monitors |
| `PATCH` | `/api/v1/integrations/monitors/events/{event_id}` | Annotate Monitor Event |
| `GET` | `/api/v1/integrations/native/monitors` | List Native Monitors |
| `POST` | `/api/v1/integrations/native/monitors` | Create Native Monitor |
| `DELETE` | `/api/v1/integrations/native/monitors/{monitor_id}` | Delete Native Monitor |
| `GET` | `/api/v1/integrations/registry` | Get Registry |
| `DELETE` | `/api/v1/integrations/{integration_id}` | Delete Integration |
| `PATCH` | `/api/v1/integrations/{integration_id}` | Update Integration |
| `GET` | `/api/v1/integrations/{integration_id}/monitors` | List Monitors For Integration |
| `PATCH` | `/api/v1/integrations/{integration_id}/monitors/{monitor_id}` | Update Monitor Link |
| `POST` | `/api/v1/integrations/{integration_id}/test` | Test Integration |
| `GET` | `/api/v1/integrations/{provider}/config` | List Configs |
| `POST` | `/api/v1/integrations/{provider}/config` | Create Config |
| `DELETE` | `/api/v1/integrations/{provider}/config/{config_id}` | Delete Config |
| `GET` | `/api/v1/integrations/{provider}/config/{config_id}` | Get Config |
| `PUT` | `/api/v1/integrations/{provider}/config/{config_id}` | Update Config |
| `POST` | `/api/v1/integrations/{provider}/config/{config_id}/test` | Test Config |

### `intelligence` — 3 operations

| Method | Path | Operation |
|---|---|---|
| `GET` | `/api/v1/intel/blast-radius/{asset_type}/{asset_id}` | Get Blast Radius |
| `GET` | `/api/v1/intel/capacity-forecasts` | List Capacity Forecasts |
| `GET` | `/api/v1/intel/resource-efficiency` | List Resource Efficiency |

### `ip-check` — 1 operations

| Method | Path | Operation |
|---|---|---|
| `POST` | `/api/v1/ip-check` | Check Ip |

### `ipam` — 6 operations

| Method | Path | Operation |
|---|---|---|
| `GET` | `/api/v1/ipam` | List Ip Addresses |
| `POST` | `/api/v1/ipam` | Create Ip Address |
| `POST` | `/api/v1/ipam/scan/{network_id}` | Scan Network Addresses |
| `DELETE` | `/api/v1/ipam/{ip_id}` | Delete Ip Address |
| `GET` | `/api/v1/ipam/{ip_id}` | Get Ip Address |
| `PATCH` | `/api/v1/ipam/{ip_id}` | Update Ip Address |

### `kb` — 10 operations

| Method | Path | Operation |
|---|---|---|
| `GET` | `/api/v1/kb/hostname` | List Hostname |
| `POST` | `/api/v1/kb/hostname` | Create Hostname |
| `GET` | `/api/v1/kb/hostname/export` | Export Hostname |
| `DELETE` | `/api/v1/kb/hostname/{entry_id}` | Delete Hostname |
| `PUT` | `/api/v1/kb/hostname/{entry_id}` | Update Hostname |
| `GET` | `/api/v1/kb/oui` | List Oui |
| `POST` | `/api/v1/kb/oui` | Create Oui |
| `GET` | `/api/v1/kb/oui/export` | Export Oui |
| `DELETE` | `/api/v1/kb/oui/{prefix}` | Delete Oui |
| `PUT` | `/api/v1/kb/oui/{prefix}` | Update Oui |

### `logs` — 4 operations

| Method | Path | Operation |
|---|---|---|
| `DELETE` | `/api/v1/logs` | Clear Logs |
| `GET` | `/api/v1/logs` | List Logs |
| `GET` | `/api/v1/logs/actions` | List Actions |
| `GET` | `/api/v1/logs/stream` | Stream Logs |

### `maps` — 8 operations

| Method | Path | Operation |
|---|---|---|
| `GET` | `/api/v1/maps` | List Maps |
| `POST` | `/api/v1/maps` | Create Map |
| `POST` | `/api/v1/maps/pin` | Pin Entity |
| `DELETE` | `/api/v1/maps/pin/{entity_type}/{entity_id}` | Unpin Entity |
| `DELETE` | `/api/v1/maps/{map_id}` | Delete Map |
| `PATCH` | `/api/v1/maps/{map_id}` | Update Map |
| `POST` | `/api/v1/maps/{map_id}/entities` | Assign Entity |
| `DELETE` | `/api/v1/maps/{map_id}/entities/{entity_type}/{entity_id}` | Remove Entity |

### `misc` — 5 operations

| Method | Path | Operation |
|---|---|---|
| `GET` | `/api/v1/misc` | List Misc |
| `POST` | `/api/v1/misc` | Create Misc Item |
| `DELETE` | `/api/v1/misc/{item_id}` | Delete Misc Item |
| `GET` | `/api/v1/misc/{item_id}` | Get Misc Item |
| `PATCH` | `/api/v1/misc/{item_id}` | Patch Misc Item |

### `monitors` — 18 operations

| Method | Path | Operation |
|---|---|---|
| `GET` | `/api/v1/monitors` | List Monitors |
| `POST` | `/api/v1/monitors` | Create Monitor |
| `GET` | `/api/v1/monitors/overview` | Monitors Overview |
| `GET` | `/api/v1/monitors/target-summary` | Target Summary |
| `POST` | `/api/v1/monitors/target/{target_type}/{target_id}` | Create Target Monitor |
| `POST` | `/api/v1/monitors/target/{target_type}/{target_id}/check` | Run Target Check |
| `POST` | `/api/v1/monitors/target/{target_type}/{target_id}/pause` | Pause Target Monitor |
| `POST` | `/api/v1/monitors/target/{target_type}/{target_id}/resume` | Resume Target Monitor |
| `DELETE` | `/api/v1/monitors/{monitor_id}` | Delete Monitor |
| `GET` | `/api/v1/monitors/{monitor_id}` | Get Monitor |
| `PATCH` | `/api/v1/monitors/{monitor_id}` | Update Monitor |
| `POST` | `/api/v1/monitors/{monitor_id}/check` | Run Immediate Check |
| `GET` | `/api/v1/monitors/{monitor_id}/events` | Get Events |
| `GET` | `/api/v1/monitors/{monitor_id}/history` | Get History |
| `POST` | `/api/v1/monitors/{monitor_id}/pause` | Pause Monitor |
| `GET` | `/api/v1/monitors/{monitor_id}/probe-runs` | Get Probe Runs |
| `POST` | `/api/v1/monitors/{monitor_id}/resume` | Resume Monitor |
| `GET` | `/api/v1/monitors/{monitor_id}/uptime` | Get Uptime |

### `networks` — 14 operations

| Method | Path | Operation |
|---|---|---|
| `GET` | `/api/v1/networks` | List Networks |
| `POST` | `/api/v1/networks` | Create Network |
| `DELETE` | `/api/v1/networks/{network_id}` | Delete Network |
| `GET` | `/api/v1/networks/{network_id}` | Get Network |
| `PATCH` | `/api/v1/networks/{network_id}` | Patch Network |
| `GET` | `/api/v1/networks/{network_id}/hardware-members` | List Hardware Members |
| `POST` | `/api/v1/networks/{network_id}/hardware-members` | Add Hardware Member |
| `DELETE` | `/api/v1/networks/{network_id}/hardware-members/{hardware_id}` | Remove Hardware Member |
| `GET` | `/api/v1/networks/{network_id}/members` | List Members |
| `POST` | `/api/v1/networks/{network_id}/members` | Add Member |
| `DELETE` | `/api/v1/networks/{network_id}/members/{compute_id}` | Remove Member |
| `GET` | `/api/v1/networks/{network_id}/peers` | List Peers |
| `POST` | `/api/v1/networks/{network_id}/peers` | Add Peer |
| `DELETE` | `/api/v1/networks/{network_id}/peers/{peer_network_id}` | Remove Peer |

### `notifications` — 9 operations

| Method | Path | Operation |
|---|---|---|
| `GET` | `/api/v1/notifications/routes` | List Routes |
| `POST` | `/api/v1/notifications/routes` | Create Route |
| `DELETE` | `/api/v1/notifications/routes/{route_id}` | Delete Route |
| `GET` | `/api/v1/notifications/sinks` | List Sinks |
| `POST` | `/api/v1/notifications/sinks` | Create Sink |
| `DELETE` | `/api/v1/notifications/sinks/{sink_id}` | Delete Sink |
| `PATCH` | `/api/v1/notifications/sinks/{sink_id}` | Update Sink |
| `POST` | `/api/v1/notifications/sinks/{sink_id}/test` | Test Sink |
| `PUT` | `/api/v1/notifications/sinks/{sink_id}/toggle` | Toggle Sink |

### `oauth` — 8 operations

| Method | Path | Operation |
|---|---|---|
| `GET` | `/api/v1/auth/exchange` | Exchange Auth Code |
| `GET` | `/api/v1/auth/oauth/github` | Github Authorize |
| `GET` | `/api/v1/auth/oauth/github/callback` | Github Callback |
| `GET` | `/api/v1/auth/oauth/google` | Google Authorize |
| `GET` | `/api/v1/auth/oauth/google/callback` | Google Callback |
| `GET` | `/api/v1/auth/oauth/oidc/{provider_slug}` | Oidc Authorize |
| `GET` | `/api/v1/auth/oauth/oidc/{provider_slug}/callback` | Oidc Callback |
| `GET` | `/api/v1/auth/oauth/providers` | List Oauth Providers |

### `proxmox` — 10 operations

| Method | Path | Operation |
|---|---|---|
| `GET` | `/api/v1/integrations/proxmox` | List Proxmox Configs |
| `POST` | `/api/v1/integrations/proxmox` | Create Proxmox Config |
| `GET` | `/api/v1/integrations/proxmox/cluster-overview` | Get Cluster Overview |
| `DELETE` | `/api/v1/integrations/proxmox/{integration_id}` | Delete Proxmox Config |
| `GET` | `/api/v1/integrations/proxmox/{integration_id}` | Get Proxmox Config |
| `PUT` | `/api/v1/integrations/proxmox/{integration_id}` | Update Proxmox Config |
| `POST` | `/api/v1/integrations/proxmox/{integration_id}/discover` | Discover Proxmox Cluster |
| `POST` | `/api/v1/integrations/proxmox/{integration_id}/nodes/{node}/{vm_type}/{vmid}/action` | Proxmox Vm Action |
| `GET` | `/api/v1/integrations/proxmox/{integration_id}/status` | Get Proxmox Status |
| `POST` | `/api/v1/integrations/proxmox/{integration_id}/test` | Test Proxmox Connection |

### `search` — 1 operations

| Method | Path | Operation |
|---|---|---|
| `GET` | `/api/v1/search` | Search |

### `security` — 1 operations

| Method | Path | Operation |
|---|---|---|
| `GET` | `/api/v1/security/status` | Get Security Status |

### `services` — 19 operations

| Method | Path | Operation |
|---|---|---|
| `GET` | `/api/v1/services` | List Services |
| `POST` | `/api/v1/services` | Create Service |
| `POST` | `/api/v1/services/check-ip` | Check Service Ip |
| `DELETE` | `/api/v1/services/{service_id}` | Delete Service |
| `GET` | `/api/v1/services/{service_id}` | Get Service |
| `PATCH` | `/api/v1/services/{service_id}` | Patch Service |
| `GET` | `/api/v1/services/{service_id}/dependencies` | Get Dependencies |
| `POST` | `/api/v1/services/{service_id}/dependencies` | Add Dependency |
| `DELETE` | `/api/v1/services/{service_id}/dependencies/{depends_on_id}` | Remove Dependency |
| `GET` | `/api/v1/services/{service_id}/discovery` | Get Service Discovery |
| `GET` | `/api/v1/services/{service_id}/external-dependencies` | Get External Deps |
| `POST` | `/api/v1/services/{service_id}/external-dependencies` | Add External Dep |
| `DELETE` | `/api/v1/services/{service_id}/external-dependencies/{relation_id}` | Remove External Dep |
| `GET` | `/api/v1/services/{service_id}/misc` | Get Service Misc |
| `POST` | `/api/v1/services/{service_id}/misc` | Add Misc Link |
| `DELETE` | `/api/v1/services/{service_id}/misc/{misc_id}` | Remove Misc Link |
| `GET` | `/api/v1/services/{service_id}/storage` | Get Service Storage |
| `POST` | `/api/v1/services/{service_id}/storage` | Add Storage Link |
| `DELETE` | `/api/v1/services/{service_id}/storage/{storage_id}` | Remove Storage Link |

### `settings` — 13 operations

| Method | Path | Operation |
|---|---|---|
| `GET` | `/api/v1/settings` | Get Settings |
| `PUT` | `/api/v1/settings` | Put Settings |
| `PATCH` | `/api/v1/settings/acme-dns` | Patch Acme Dns |
| `GET` | `/api/v1/settings/oauth` | Get Oauth Settings |
| `PATCH` | `/api/v1/settings/oauth` | Update Oauth Settings |
| `GET` | `/api/v1/settings/opnsense/test` | Test Opnsense Connection |
| `POST` | `/api/v1/settings/reset` | Reset Settings |
| `GET` | `/api/v1/settings/roles` | List Roles |
| `POST` | `/api/v1/settings/roles` | Create Role |
| `DELETE` | `/api/v1/settings/roles/{role_id}` | Delete Role |
| `PUT` | `/api/v1/settings/roles/{role_id}` | Update Role |
| `PATCH` | `/api/v1/settings/smtp` | Patch Smtp |
| `POST` | `/api/v1/settings/smtp/test` | Test Smtp |

### `sites` — 5 operations

| Method | Path | Operation |
|---|---|---|
| `GET` | `/api/v1/sites` | List Sites |
| `POST` | `/api/v1/sites` | Create Site |
| `DELETE` | `/api/v1/sites/{site_id}` | Delete Site |
| `GET` | `/api/v1/sites/{site_id}` | Get Site |
| `PATCH` | `/api/v1/sites/{site_id}` | Update Site |

### `storage` — 5 operations

| Method | Path | Operation |
|---|---|---|
| `GET` | `/api/v1/storage` | List Storage |
| `POST` | `/api/v1/storage` | Create Storage |
| `DELETE` | `/api/v1/storage/{storage_id}` | Delete Storage |
| `GET` | `/api/v1/storage/{storage_id}` | Get Storage |
| `PATCH` | `/api/v1/storage/{storage_id}` | Patch Storage |

### `system` — 2 operations

| Method | Path | Operation |
|---|---|---|
| `GET` | `/api/v1/system/stats` | Get System Stats |
| `GET` | `/api/v1/system/update` | Get Update Status |

### `tags` — 2 operations

| Method | Path | Operation |
|---|---|---|
| `GET` | `/api/v1/tags` | List Tags |
| `PATCH` | `/api/v1/tags/{tag_id}` | Update Tag |

### `telemetry` — 8 operations

| Method | Path | Operation |
|---|---|---|
| `GET` | `/api/v1/hardware/entity/{entity_type}/{entity_id}` | Get Entity Telemetry |
| `GET` | `/api/v1/hardware/{hardware_id}/telemetry` | Get Telemetry |
| `POST` | `/api/v1/hardware/{hardware_id}/telemetry/config` | Configure Telemetry |
| `POST` | `/api/v1/hardware/{hardware_id}/telemetry/poll` | Poll Now |
| `GET` | `/api/v1/telemetry/entity/{entity_type}/{entity_id}` | Get Entity Telemetry |
| `GET` | `/api/v1/telemetry/{hardware_id}/telemetry` | Get Telemetry |
| `POST` | `/api/v1/telemetry/{hardware_id}/telemetry/config` | Configure Telemetry |
| `POST` | `/api/v1/telemetry/{hardware_id}/telemetry/poll` | Poll Now |

### `tenants` — 12 operations

| Method | Path | Operation |
|---|---|---|
| `DELETE` | `/api/v1/tenants` | Tenancy Disabled |
| `GET` | `/api/v1/tenants` | Tenancy Disabled |
| `OPTIONS` | `/api/v1/tenants` | Tenancy Disabled |
| `PATCH` | `/api/v1/tenants` | Tenancy Disabled |
| `POST` | `/api/v1/tenants` | Tenancy Disabled |
| `PUT` | `/api/v1/tenants` | Tenancy Disabled |
| `DELETE` | `/api/v1/tenants/{legacy_path}` | Tenancy Disabled |
| `GET` | `/api/v1/tenants/{legacy_path}` | Tenancy Disabled |
| `OPTIONS` | `/api/v1/tenants/{legacy_path}` | Tenancy Disabled |
| `PATCH` | `/api/v1/tenants/{legacy_path}` | Tenancy Disabled |
| `POST` | `/api/v1/tenants/{legacy_path}` | Tenancy Disabled |
| `PUT` | `/api/v1/tenants/{legacy_path}` | Tenancy Disabled |

### `timezones` — 1 operations

| Method | Path | Operation |
|---|---|---|
| `GET` | `/api/v1/timezones` | Get Timezones |

### `topologies` — 7 operations

| Method | Path | Operation |
|---|---|---|
| `GET` | `/api/v1/topologies` | List Topologies |
| `POST` | `/api/v1/topologies` | Create Topology |
| `DELETE` | `/api/v1/topologies/{topology_id}` | Delete Topology |
| `GET` | `/api/v1/topologies/{topology_id}` | Get Topology |
| `PUT` | `/api/v1/topologies/{topology_id}` | Update Topology |
| `GET` | `/api/v1/topologies/{topology_id}/graph` | Export Cytoscape |
| `PUT` | `/api/v1/topologies/{topology_id}/nodes` | Bulk Update Nodes |

### `topology-ws` — 1 operations

| Method | Path | Operation |
|---|---|---|
| `GET` | `/api/v1/topology/ws/status` | Topology Ws Status |

### `users` — 9 operations

| Method | Path | Operation |
|---|---|---|
| `GET` | `/api/v1/users/me` | Users:Current User |
| `PATCH` | `/api/v1/users/me` | Users:Patch Current User |
| `PATCH` | `/api/v1/users/me/password` | Change Password |
| `DELETE` | `/api/v1/users/me/sessions` | Revoke All Other Sessions |
| `GET` | `/api/v1/users/me/sessions` | List My Sessions |
| `DELETE` | `/api/v1/users/me/sessions/{session_id}` | Revoke Session |
| `DELETE` | `/api/v1/users/{id}` | Users:Delete User |
| `GET` | `/api/v1/users/{id}` | Users:User |
| `PATCH` | `/api/v1/users/{id}` | Users:Patch User |

### `vault` — 4 operations

| Method | Path | Operation |
|---|---|---|
| `POST` | `/api/v1/admin/vault/initialize` | Initialize Vault Key |
| `POST` | `/api/v1/admin/vault/rotate` | Rotate Vault Key |
| `POST` | `/api/v1/admin/vault/test` | Test Vault Decryption |
| `GET` | `/api/v1/health/vault` | Get Vault Health |

### `vlans` — 5 operations

| Method | Path | Operation |
|---|---|---|
| `GET` | `/api/v1/vlans` | List Vlans |
| `POST` | `/api/v1/vlans` | Create Vlan |
| `DELETE` | `/api/v1/vlans/{vlan_pk}` | Delete Vlan |
| `GET` | `/api/v1/vlans/{vlan_pk}` | Get Vlan |
| `PATCH` | `/api/v1/vlans/{vlan_pk}` | Update Vlan |

### `windscribe` — 8 operations

| Method | Path | Operation |
|---|---|---|
| `GET` | `/api/v1/devices/{hardware_id}/threat-profile` | Get Device Threat Profile |
| `GET` | `/api/v1/network/attack-surface` | Get Attack Surface |
| `GET` | `/api/v1/network/privacy-score` | Get Network Privacy Score |
| `GET` | `/api/v1/network/privacy-score/history` | Get Network Privacy Score History |
| `GET` | `/api/v1/network/threat-alerts` | Get Network Threat Alerts |
| `DELETE` | `/api/v1/privacy-findings/ignore` | Unignore Privacy Finding |
| `POST` | `/api/v1/privacy-findings/ignore` | Ignore Privacy Finding |
| `GET` | `/api/v1/privacy-findings/ignores` | List Privacy Finding Ignores |

---

## Keeping this page honest

The catalogue above is the live OpenAPI schema, rendered. To reproduce it after a route changes,
start the server and read the schema it serves:

```bash
# Native install: the backend listens on 127.0.0.1:8000 behind nginx.
curl -s http://127.0.0.1:8000/api/openapi.json > openapi.json

# Through the published listener instead (any mode):
curl -sk https://<your-host>/api/openapi.json > openapi.json
```

Every operation, path and summary in the tables comes from `paths` in that document; the tag
headings are its `tags`. Operations the schema marks `include_in_schema=False` — the Prometheus
endpoint and the static mounts — are documented in prose above instead, because they are real
routes that a generated table would silently omit.

---

## Related

- [cb CLI Tool](../cb-cli.md) — the administrative surface that does not go through HTTP
- [Configuration precedence and environment catalogue](configuration-precedence.md)
- [Authentication & Access](../auth-access.md) — setting up OAuth, MFA and invites
- [Compatibility policy](../release/1.0.0-compatibility-policy.md) — what may change and when
- [Threat model](../security/threat-model.md) — the trust boundaries this API sits on
