# Threat Model

A STRIDE analysis of Circuit Breaker as it is built in this release, not of a generic web
application. Every mitigation named below is a control that exists in the shipped code; every
residual risk named below is one we have not closed.

Read it alongside the [1.0.0 support contract](../release/1.0.0-support-contract.md), which defines
the deployment boundary this model assumes, and [Deployment & Security](../deployment-security.md),
which is the operator-facing hardening guide.

---

## Scope and method

**In scope:** the control-plane server (API, workers, bundled web UI), the `cb-agent` fleet and its
wire protocol, the credential vault, the mono-container appliance, and the data at rest that all of
these share.

**Out of scope by decision, not by omission:**

| Excluded | Why |
|---|---|
| Multi-tenant isolation | 1.0 is single-tenant by decision — [ADR-0003](../adr/0003-defer-true-multi-tenancy.md). One deployment is one trust boundary. Tenant-shaped columns survive as inert compatibility metadata and are **not** a security control. |
| Direct internet exposure | [Unsupported for 1.0.0](../release/1.0.0-support-contract.md#deployment-support-matrix). The model assumes LAN or VPN reachability. |
| High availability | [Unsupported for 1.0.0](../operations/appliance-and-availability.md). A single active application server. |
| An already-compromised host or database | Consistent with the [disclosure policy's scope](vulnerability-disclosure.md#scope). Root on the host owns the vault key by definition. |

**Method:** the system is decomposed into six trust boundaries; each is analysed against the six
STRIDE categories; each finding names the control that addresses it and what is left over.

---

## What is worth stealing

Ordered by what an attacker gains, not by how the data is stored.

| Asset | Why it matters | Where it lives |
|---|---|---|
| **The inventory itself** | A complete map of the operator's network: hosts, addresses, services, versions, dependencies and known CVEs. This is finished reconnaissance. Losing it is worse than losing most individual credentials. | PostgreSQL |
| **Vault-encrypted credentials** | SMTP passwords, Proxmox API tokens, SNMP community strings, iDRAC/iLO credentials — each of which is privileged access to something else. | PostgreSQL, encrypted with the vault key |
| **The vault key** | Decrypts every one of the above. A Fernet key, 32 random bytes. | `CB_VAULT_KEY`, `$CB_DATA_DIR/.env`, and **in plaintext inside every full-state snapshot** |
| **The JWT signing secret** | Forges any session, for any user, at any role. | `app_settings.jwt_secret`, or `CB_JWT_SECRET` |
| **The server's agent identity key** | The X25519 static key the Noise IK handshake authenticates. Holding it lets an attacker impersonate the server to the whole fleet. | `app_settings.agent_server_private_key`, itself vault-encrypted |
| **Agent capability grants** | Discovery and probe execution across the operator's private networks. Not code execution, but directed network activity from a trusted position. | PostgreSQL, enforced on both sides |
| **The audit log** | The record of what happened. Its value to an attacker is in destroying it. | PostgreSQL, SHA-256 hash chain |
| **Sessions and API tokens** | Direct authenticated access. | Cookies, `Authorization` headers, salted HMAC at rest |
| **The setup token** | Creates the first administrator on an unbootstrapped instance. | `CB_SETUP_TOKEN`, or `$CB_DATA_DIR/bootstrap-setup-token` at mode `0600` |

---

## Trust boundaries

```text
                     ┌─ TB1 ─┐
   browser  ─────────┤ TLS   ├──────►  nginx  ──TB2──►  backend API
                     └───────┘        (in-appliance)      │
                                                          │
   cb-agent ══TB3══►  /api/v1/agents/enroll  ─────────────┤   Noise IK over WSS,
            ══TB3══►  /api/v1/agents/link                 │   no session auth
                                                          │
                                                          ├──TB5──►  public internet
                                                          │          (webhooks, feeds,
                                                          │           release check)
                                                          │
                              ┌───────────── TB6 ─────────┴──────────────┐
                              │  PostgreSQL │ Redis │ NATS │ file store  │
                              └──────────────────────────────────────────┘

   cb-agent ══TB4══►  the monitored network  (ICMP, TCP, HTTP, DNS, Docker socket)

   TB1  browser ↔ TLS terminator
   TB2  reverse proxy ↔ backend (the X-Forwarded-* trust decision)
   TB3  unauthenticated caller ↔ the agent wire protocol
   TB4  agent ↔ the operator's private networks
   TB5  backend ↔ the public internet (outbound only)
   TB6  application ↔ its own data stores, inside one appliance
```

A seventh boundary — **users inside one deployment** — is authorization, not isolation. RBAC
separates what a `viewer` may do from what an `admin` may do. It is not a data boundary, and it is
not a substitute for separate deployments.

---

## TB1 — Browser to TLS terminator

Both shipped install paths put nginx in front of the backend and terminate TLS themselves.

| STRIDE | Threat | Mitigation in this code | Residual |
|---|---|---|---|
| **S** | Session theft from client-side code | The session token is an `HttpOnly`, `SameSite=Strict` cookie; `Secure` whenever the request is TLS or a trusted proxy asserts it. JavaScript cannot read it. | A token *may* still be presented as `Authorization: Bearer`, which a client that stores it insecurely can leak. That is the client's choice, not the server's. |
| **S** | Cross-site request forgery | Double-submit: mutating methods carrying `cb_session` must echo the readable `cb_csrf` cookie in `X-CSRF-Token`. `SameSite=Strict` is the second layer. | The session-establishing endpoints are exempt by prefix, as they must be — they are what issues the pair. |
| **T** | Script injection / clickjacking | `Content-Security-Policy` with `script-src 'self' 'unsafe-inline'` and `frame-ancestors 'none'`; `X-Frame-Options: DENY`; `X-Content-Type-Options: nosniff`; `Referrer-Policy: strict-origin-when-cross-origin`; a `Permissions-Policy` denying camera, microphone, geolocation, payment, USB and the motion sensors. | `style-src` permits `'unsafe-inline'`, and the policy allows Gravatar, Google Fonts and Open-Meteo origins the UI genuinely uses. The CSP is duplicated in five files (backend middleware, both Docker nginx configs, both native nginx configs); `tests/build/test_nginx_spa_security_headers.py` holds them byte-identical. `script-src` names `'unsafe-inline'` rather than `'strict-dynamic'` because the bundle carries no nonce: under CSP Level 3 `'strict-dynamic'` makes the browser ignore `'self'` and every host source, so a nonce-less policy allows no script at all. |
| **I** | Downgrade to plaintext | HSTS (`max-age=63072000; includeSubDomains; preload`) is set — but **only** when the request is genuinely secure, because any peer able to trigger HSTS could pin a host to a scheme it does not serve. | A fresh install serves a self-signed certificate; the first visit is trust-on-first-use unless you install your own. |
| **D** | Credential stuffing, brute force | Per-route limits on `auth`, `mfa_verify`, `ip_check`, `scan` and `telemetry`, keyed by the trusted client identity; account lockout via `locked_until`; MFA. | Limits are keyed by client identity, so a distributed attacker gets one bucket per source. |
| **E** | Privilege escalation through the browser | Role and scope checks run server-side on every request; the UI is not a control. | — |

---

## TB2 — Reverse proxy to backend

This is the boundary that fails quietly, and it is worth its own section.

`X-Forwarded-For`, `X-Forwarded-Proto` and `X-Forwarded-Host` are believed **only** when the socket
peer is inside `CB_TRUSTED_PROXY_CIDRS` (default `127.0.0.1/32,::1/128`, correct for the bundled
nginx and wrong for anything else).

| STRIDE | Threat | Mitigation | Residual |
|---|---|---|---|
| **S** | A client spoofs its source address to escape rate limiting or an IP allow-list | Forwarded headers are discarded from an untrusted peer; the socket peer is used instead. | Anything inside the configured CIDRs can assert any client IP. The range must be exactly your proxy. |
| **S** | A plain-HTTP client claims `X-Forwarded-Proto: https` to obtain a `Secure` cookie, an HSTS pin, or to pass `CB_WS_REQUIRE_WSS` | Same trust rule, applied in `auth_cookie`, `security_headers` and the WebSocket secure check. | — |
| **D** | Rate limiting collapses onto the proxy's IP | Documented failure mode with the exact symptom. | Misconfiguration is silent: nothing fails, everyone shares one bucket. **[Remote Access](../remote-access.md#trusted-proxies) exists because of this.** |

---

## TB3 — The agent wire protocol

`/api/v1/agents/enroll` and `/api/v1/agents/link` are mounted **deliberately without session
authentication**. The Noise IK handshake is their authentication. Everything else about them
follows from that.

### How authentication actually works

The server holds one static X25519 keypair — generated on first use, stored vault-encrypted in
`app_settings.agent_server_private_key`, cached for the process lifetime. A Noise **IK** handshake
means the initiator must already know the responder's static public key, so the handshake
authenticates *the server to the agent*. The agent's own device key is learned during that
handshake and recorded; it is **not** pre-authorised.

That asymmetry is why enrollment ends in a human decision rather than a cryptographic one: a
successful handshake proves the caller is talking to the right server, and nothing more. An
operator approves the fingerprint.

| STRIDE | Threat | Mitigation | Residual |
|---|---|---|---|
| **S** | An attacker impersonates the server and harvests agent traffic | Noise IK plus TLS pinning: for a self-signed deployment the agent replaces chain and hostname verification with an exact match on the base64 SHA-256 of the served leaf's SubjectPublicKeyInfo, applied to the enroll socket, the link socket **and** binary downloads. | The pin is distributed with the install command. Anyone who can serve that install command can set the pin — the install channel is the root of trust. |
| **S** | An attacker enrolls a rogue agent | Enrollment creates a **pending** row and nothing more. Capabilities, scope and probe assignments arrive only after an administrator approves the fingerprint. A device key on a `revoked` or `rejected` row is refused outright — there is no silent re-enrollment. | An administrator who approves without checking the fingerprint has approved an attacker. The pairing code is a *selector*, not a credential. |
| **T** | Frame tampering or replay on the link | All post-handshake frames are Noise-encrypted and sequence-numbered; transport ciphers are rekeyed in place on a timer using the Noise spec §11.3 REKEY; `hello` timestamps are checked against a ±60 s clock-skew tolerance. | A device key stolen from an agent host authenticates as that agent until it is revoked. Host compromise is the operator's boundary. |
| **R** | An agent denies work it performed | Agent events and probe runs are recorded server-side; scope decisions carry machine-readable reasons. | — |
| **I** | Enumerating which limit an anonymous caller tripped | Rate-limited enrollment closes bare with code `1013` and no payload — the endpoint has no cipher yet, and a plaintext reason would tell an anonymous caller which limit fired. | — |
| **D** | Enrollment flood | Checked **before the first handshake byte is read**: 20 attempts per IP per 60 s, 200 globally per 60 s. A concurrent-pending cap of 100 rows is enforced under a cross-worker Redis lock held past the commit, so two workers cannot both slip under it. Pairing-code guessing is limited to 10 misses per IP and 50 globally per 15 minutes; codes are 60-bit, single-use, and expire in 15 minutes. Handshake timeout 10 s. | The caps are global, so a flood still denies enrollment to a legitimate agent for the window. That is the intended trade. |
| **E** | An approved agent widens its own scope | Scope is **derived, not declared**: from the private networks the agent reports as directly attached, plus admin-approved `additional_cidrs`, minus `excluded_cidrs`. Both the server evaluator and the agent evaluator must pass a destination, and they are pinned against a shared corpus so they cannot drift. Prefixes wider than `/16` (IPv4) or `/48` (IPv6) are refused whatever the grant says; special-use ranges — loopback, link-local, multicast, and `fd00:ec2::254/128` — are denied on *overlap*, not containment. A dispatch built against a stale scope version is refused rather than run. | An agent host under attacker control can lie about its attached interfaces, which moves its `direct_private` scope. It cannot exceed the admin-approved allow-list, and it cannot reach special-use space. |

---

## TB4 — Agent to the monitored network

The agent is the only component that deliberately sends traffic into the operator's private
networks. It binds **no listening socket**; every connection is outbound.

| STRIDE | Threat | Mitigation | Residual |
|---|---|---|---|
| **T** | The agent is used as a scanning platform against out-of-scope hosts | The AGT-08 guarantee: a refused destination is refused *before a socket is dialled or a name is resolved*, and reported with the evaluator's own reason (`out_of_scope`, `special_use`, `excluded_cidr`, `prefix_too_wide`, `not_directly_connected`), never as a fabricated empty result. Hostnames are judged by every resolved address independently, which makes a rebinding resolver useless. | Within an approved scope, the agent does exactly what discovery and probing mean: connect to hosts and ports. That is the product. |
| **I** | Over-collection from the host | Capabilities are individually opt-out at approval. `host_telemetry` ships with virtual interfaces and Docker container inspection **off**. Docker access additionally requires `docker` group membership on the host. | An enabled `include_docker` grant reads container metadata from the local Docker socket. |
| **E** | Privilege on the agent host | The agent runs as a service user; ICMP uses unprivileged datagram sockets rather than `CAP_NET_RAW`. | Elevated capabilities the unit does grant are enumerated in [cb-agent § Permissions](../agent.md#permissions). |
| **D** | A disconnected agent fills the host disk | The spool is capped at 64 MiB (`spool_cap_bytes`); at the cap the **oldest** frames are dropped. Control frames are never spooled. Catch-up after reconnect is paced at 4 frames or 256 KiB per 100 ms so a backlog cannot stall live telemetry. | Data older than the cap is lost during a long outage — by design, and visible as a flat spool depth in the fleet view. |

---

## TB5 — Backend to the public internet

Outbound requests are the SSRF surface: several of them take a URL an authenticated user supplied.

Every outbound client passes through one validator with a **policy chosen for the use case**
(`app/core/url_validation.py`). The policy validates the scheme, rejects userinfo in the URL,
resolves **all** DNS answers, and refuses the request if *any* resolved address is disallowed.

| Policy | Schemes | Private | Loopback |
|---|---|---|---|
| Webhook | http, https | no | no |
| Threat feed | https only | no | no |
| LAN integration | http, https | yes | no |
| Monitor target | http, https | yes | **yes** |
| OIDC | http, https | yes | no |
| Egress proxy | http, https | yes | yes |

Link-local is refused under **every** policy, which is what takes `169.254.169.254` — the cloud
metadata service — off the table regardless of use case.

| STRIDE | Threat | Mitigation | Residual |
|---|---|---|---|
| **I** | SSRF to the metadata service or an internal admin endpoint | Per-policy address screening on every literal, every resolved answer and every redirect hop. | The monitor-target policy allows loopback and private space on purpose — watching your own LAN and your own host is the product. An editor who can create monitors can therefore probe the host. That is authorization working as designed, not an SSRF bypass. |
| **I** | Uncontrolled egress from the appliance | `CB_EGRESS_PROXY_URL` routes public outbound clients through a forward proxy; an invalid value fails startup even in degraded mode. Running without one must be recorded as a decision (`CB_ALLOW_DIRECT_EGRESS`). | Every shipped template sets `CB_ALLOW_DIRECT_EGRESS=true`, because most single-node hosts have no forward proxy. The decision defaults to "no proxy". |
| **I** | Version disclosure to a third party | The daily release check sends an unauthenticated `GET` to `api.github.com` with `User-Agent: circuit-breaker/<version>`. **This discloses the running version and the source IP once a day**, and is documented as such rather than buried. `CB_UPDATE_CHECK=false`, `CB_AIRGAP=true`, or the Settings switch each stop the socket being opened. | On by default. The trade is deliberate: an instance that cannot learn it is out of date is the more common real-world harm. |
| **D** | A slow or hostile endpoint ties up workers | An outbound circuit breaker bounded at 500 tracked endpoints with a 3600 s entry TTL; threat-feed responses are capped at 5 MB. | — |

Note the deliberate asymmetry: `GET /api/v1/health` withholds the version from an anonymous caller
as fingerprinting material, and `GET /api/v1/system/update` is admin-only — yet the release check
discloses that same value outbound daily. Both choices are intentional and both are stated.

---

## TB6 — The appliance boundary

The mono container runs PostgreSQL, PgBouncer, Redis, NATS, nginx, the backend and the workers
together under supervisord, in **one image, on one node**. This is the single largest structural
decision in the model.

**What that buys:** every data store is loopback-only. There is no database port on the network, no
Redis on the network, no NATS on the network. The attack surface between the application and its
data is a Unix-level one, not a network one.

**What it costs:** there is no isolation *between* those components. A vulnerability that yields
code execution as the backend user is adjacent to the PostgreSQL data directory, the Redis dump and
the vault key file. Compromise of the application is compromise of the data.

| STRIDE | Threat | Mitigation | Residual |
|---|---|---|---|
| **T** | Modifying the running image | `read_only: true` root filesystem; writable scratch is size-capped `tmpfs` on `/tmp`, `/run`, `/var/log`, `/var/lib/nginx`, `/var/lib/postgresql`, discarded on restart. | The `/data` bind mount is writable by definition — it is the state. |
| **E** | Escaping the container | `no-new-privileges:true`; `cap_drop: ALL` followed by a named add-back list. | The add-back list is `NET_RAW`, `NET_BIND_SERVICE`, `CHOWN`, `FOWNER`, `SETUID`, `SETGID`, `DAC_OVERRIDE` — needed for SNMP/ICMP polling, low ports, the entrypoint's ownership fix, and supervisord dropping privileges. `DAC_OVERRIDE` and `SETUID` are meaningful capabilities. Narrow the list if you use neither SNMP nor ICMP and `CB_PORT` is above 1024. |
| **I** | Reading credentials at rest | Credentials are Fernet-encrypted with the vault key; only a **hash** of the key is stored in the database. The server's agent identity key is itself vault-encrypted. | The vault key is on the same host as the ciphertext. There is no external KMS in 1.0. This is a deliberate homelab trade-off. |
| **I** | Leaking secrets to disk through logs | A global log-redaction filter is installed at import time; a uvicorn access-log filter scrubs `code`, `state`, `cb_auth_code`, `cb_mfa_token`, `oauth_token` and `access_token` query parameters before anything is written. | `DEV_MODE=true` returns full stack traces in HTTP responses. It must never be set in production. |
| **I** | Backups as an exfiltration path | Snapshot archives are written mode `0600`. | **A full-state snapshot contains the vault key in plaintext** — it must, or the dump's encrypted columns are unreadable. Treat the archive itself as a credential. |
| **R** | Erasing the trail | Every audit entry stores the SHA-256 of its payload plus the previous entry's hash, so a deleted or edited row breaks the chain. Verification is an endpoint; repair requires the explicit `REPAIR_AUDIT_CHAIN` authorization. Denied destructive actions are themselves audited. | The chain is tamper-*evident*, not tamper-*proof*: an attacker with database write access can rewrite the chain wholesale. Detection depends on someone verifying it. |
| **D** | Accidental destruction | Destructive operations require `x-cb-confirmation` naming the action, an `idempotency-key` of at least 12 characters, and `x-cb-backup-verified: true` where a verified backup is required. | — |
| **D** | Dependency outage cascading into a restart storm | Liveness is deliberately separate from readiness: `/livez` touches no dependency, and health paths are excluded from the rate limiter by name so a Redis outage cannot turn a probe into a `503`. | — |
| **T** | A write accepted against a database that cannot persist it | Write admission refuses mutating `/api/` requests with `503` and a machine-readable `SERVICE_NOT_READY` / `SERVER_DRAINING` code whenever a required dependency cannot answer or the process is draining. Reads, WebSocket sessions and health endpoints stay open. | The dependency verdict is cached for `CB_HEALTH_CACHE_TTL_S` (default 2 s), which bounds — but does not eliminate — the window. |

---

## Cross-cutting: identity and sessions

| STRIDE | Threat | Mitigation | Residual |
|---|---|---|---|
| **S** | Replaying a non-session token as a session | Session JWTs carry the audience `fastapi-users:auth`, so a password-reset or MFA token is not accepted as a session. | — |
| **S** | Stolen API token used indefinitely | Tokens support expiry, rotation and revocation; at rest each is a per-token salted HMAC-SHA256 (`{salt_hex}:{hmac_hex}`), so a database read yields no usable token. | Verification must **iterate** stored tokens, because the salt is embedded and there is no direct lookup. Cost grows with the number of live tokens. |
| **S** | A revoked session still honoured | The 10-second per-process validation cache is confirmed against a shared Redis revocation marker on every hit, so a logout on one uvicorn worker is honoured by the others. When Redis is unreachable the cache is **bypassed** and every request does full database validation — degraded to slow, never to stale. | If the revocation write to Redis fails while Redis is otherwise reachable, a cached entry can survive for up to its 10-second TTL. The failure is logged. |
| **S** | Password material on the wire | The browser pre-hashes with PBKDF2-HMAC-SHA256 before sending; the server bcrypts the result for storage. | The pre-hash salt is a **deployment-wide** value (`CB_CLIENT_SALT`, defaulting to a constant), not per-user — so the wire value is password-equivalent for that deployment, and TLS is what protects it. A legacy `SHA256(password + salt)` wire format is still accepted for credentials created before the PBKDF2 format. |
| **E** | Deprecated god-mode token | `CB_API_TOKEN` is rejected: a Bearer token matching it is answered `401`, and startup logs a removal warning. | `CB_LEGACY_AUTH=true` restores the old admin grant. It exists as a rollback and must not be left enabled. |
| **E** | Hijacking first-run setup | Before an administrator exists, the admin-equivalent sentinel is granted only to the bootstrap and auth routes, `GET`/`HEAD` on settings, and `PATCH /settings/oauth`. Everything else answers `401`. Creating the first administrator additionally requires the setup token: at least 16 characters, written mode `0600` if generated, 24 h default lifetime, single-use, and replays answered `409`. | The setup window is a real window. Do not expose an unbootstrapped instance. |
| **S** | No self-service password reset to abuse | `POST /auth/forgot-password` and `POST /auth/reset-password` answer `410 Gone` and the email-reset scaffolding is removed. Recovery is administrator-mediated. | **Reset With Vault Key** remains for the case where no administrator can sign in. It requires the holder to have `CB_VAULT_KEY` — which is the master credential, so this is a deliberate equivalence, not an escalation. |

---

## Residual risk register

Consolidated, so an operator can act on it. Nothing here is hypothetical.

| # | Residual risk | Severity driver | What an operator can do |
|---|---|---|---|
| R1 | **Write admission depends on the health probe being right.** Mutating requests are refused with `503` while a required dependency cannot answer or the process is draining — but the verdict is cached briefly (`CB_HEALTH_CACHE_TTL_S`, default 2 s), so a write can be admitted against a database that has just gone away. | A narrow window, bounded by the cache TTL. | Leave the TTL short. Still act on `/readyz` at the load balancer — refusing a write is a safety net, not a routing strategy. |
| R2 | **Snapshots contain the vault key in plaintext.** | Anyone holding a backup holds every stored credential. | Store snapshots as credentials: encrypted at rest, access-controlled, off-host. |
| R3 | **No isolation inside the mono appliance.** Backend compromise is data compromise. | One boundary, not several. | Prefer a native install with host-level separation if your threat model needs it; keep the appliance off any untrusted network. |
| R4 | **`CB_TRUSTED_PROXY_CIDRS` misconfiguration is silent.** | Rate limiting collapses; `CB_WS_REQUIRE_WSS` rejects everything. | Set it to the proxy's real source range and verify after every topology change. |
| R5 | **Tenant-shaped schema is not a boundary.** | An operator may believe data is isolated when it is not. | Separate trust domains get separate deployments. `/api/v1/tenants` answers `410` on purpose. |
| R6 | **Audit chain is tamper-evident, not tamper-proof.** | Database write access defeats it. | Verify the chain on a schedule; ship audit records off-box if you need stronger assurance. |
| R7 | **Daily version disclosure to GitHub, on by default.** | Fingerprinting material leaves the network. | `CB_UPDATE_CHECK=false` or `CB_AIRGAP=true`. |
| R8 | **Default self-signed certificate.** | First contact is trust-on-first-use. | Install a real certificate, or distribute the CA. Agents pin the served key either way. |
| R9 | **`CB_ALLOW_DIRECT_EGRESS=true` in every shipped template.** | Outbound requests leave the host directly. | Point `CB_EGRESS_PROXY_URL` at a proxy and set the flag to `false`. |
| R10 | **Deployment-wide client password salt.** | The wire hash is password-equivalent for the deployment. | Terminate TLS everywhere, including internally; set `CB_CLIENT_SALT` to a deployment-specific value. |
| R11 | **API-token verification iterates every stored token.** | Cost grows with live token count. | Revoke tokens you no longer use. |
| R12 | **`CB_LEGACY_AUTH` and `DEV_MODE` re-open closed doors.** | God-mode token; stack traces in responses. | Neither belongs in a production environment file. Check with `cb config validate`. |

---

## Assumptions this model rests on

If any of these is false for your deployment, the analysis above does not hold.

1. The deployment is reachable only from a LAN or VPN, not directly from the internet.
2. The host is single-purpose and its root account is trusted; root owns the vault key.
3. One deployment serves one trust domain.
4. Administrators verify an agent fingerprint before approving enrollment.
5. The agent install command is delivered over a channel the operator controls — it carries the TLS pin.
6. Snapshots are stored somewhere at least as protected as the instance they came from.

---

## Related

- [Deployment & Security](../deployment-security.md) — the hardening guide these controls appear in
- [Secure remote access](../remote-access.md) — proxies, trusted headers, TLS ownership, ports
- [cb-agent](../agent.md) — enrollment, scope, capabilities and permissions in full
- [Privacy](privacy.md) — what data exists and what leaves the deployment
- [Vulnerability disclosure](vulnerability-disclosure.md) — how to report a finding
- [Audit Log](../audit-log.md) — chain verification and repair
