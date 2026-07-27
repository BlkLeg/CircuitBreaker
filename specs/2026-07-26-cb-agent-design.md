# cb-agent — Remote Client Agent Design

**Date:** 2026-07-26
**Status:** Approved
**Related:** `specs/2026-07-25-native-monitoring-engine-design.md` (monitor engine the remote-probe
capability feeds), `docs/remote-access.md` (Cloudflare Tunnel path this design must survive)

## Context

Circuit Breaker collects telemetry today by **pulling**: `integrations/dispatcher.py` polls
iDRAC/iLO/SNMP/Proxmox endpoints from the server, and the native monitoring engine runs
ICMP/TCP/HTTP checks from the server's own network position. Both approaches stop at the
boundaries of what the server can reach and what a remote endpoint will expose. A Linux box
with no IPMI, a subnet the server cannot route to, and a remote site behind NAT are all
invisible.

`cb-agent` is a downloadable daemon the user installs on their own machines. It connects
outbound to their Circuit Breaker instance and becomes a reporting endpoint and a network
vantage point. The user copies an install command from within the app, runs it, confirms the
enrollment in-app, and the agent shows as connected immediately.

## Decisions

| Question | Decision |
|---|---|
| Agent role (v1) | Host telemetry reporter, remote probe, local discovery. **No network relay/tunnel.** |
| Enrollment direction | Agent → app. No secret in the install command; agent prints a pairing code + magic link. |
| Runtime & packaging | Go static binary, linux amd64/arm64, systemd unit |
| Channel crypto | X25519 device identity + Noise `IK` channel nested inside WSS |
| Transport | Persistent WSS to the FastAPI backend through the existing :443 proxy, with a bounded on-disk spool |
| Binary distribution | Served by the user's own CB instance; no third-party dependency, air-gap capable |
| Agent authority | Per-agent capability grants, default-deny, dedicated non-root user |
| Data model | First-class `agents` entity with an optional `Hardware` link |
| Self-update | In-app, over the authenticated Noise channel, with automatic rollback |

### Rejected alternatives

- **Network relay / tunnel capability.** By far the largest security surface — it creates an
  inbound path into the agent's LAN. Every v1 capability is outbound-only and agent-initiated.
  Not ruled out forever; ruled out here.
- **Agent-as-direct-NATS-client.** Free durability and replay, but requires exposing 4222 with
  its own TLS and account provisioning, adds a second credential system alongside the device
  key, and **does not traverse a Cloudflare Tunnel** — which would break the remote-access path
  CB's own docs recommend.
- **HTTPS batch POST + SSE.** Simplest transport, but presence becomes heartbeat-interval-based.
  A 30-second window between "unplugged" and "shows offline" contradicts the instant-status
  requirement that motivated this work.
- **mTLS with CB as a private CA.** Standard and battle-tested, but nginx/Caddy must be
  configured to pass through or verify client certs, and a Cloudflare Tunnel breaks mTLS
  outright.
- **Enrollment token embedded in the install command.** One less step, but the token lands in
  shell history, process args, and any log that captured the command.
- **A root-owned `cb-agent-helper` daemon.** `cb-helperd` exists on the server because the
  server genuinely needs runtime privilege escalation. The agent does not; shipping a
  root-owned socket onto other people's machines is a security cost with no v1 payoff.

## 1. Architecture

Three processes and one protocol. The agent is a standalone Go daemon, the backend gains an
agent control plane, and the wire format between them is a versioned frame envelope defined
once on each side and nowhere else.

```text
┌─ agent host ──────────────┐            ┌─ CB server ─────────────────────────┐
│ cb-agent (systemd)        │            │ nginx/Caddy :443                    │
│  ├ enroll   (first run)   │            │   └ /api/agents/link  ──┐           │
│  ├ link     (WSS+Noise)   │══ WSS ════▶│                         ▼           │
│  ├ spool    (bounded)     │  outbound  │  ws_agents.py → agent_link.py       │
│  ├ capability gate        │   only     │        │ decrypt · verify · dispatch│
│  └ collectors             │            │        ▼                            │
│     host │ probe │ discover│            │  NATS: telemetry.ingest.>           │
└───────────────────────────┘            │        monitor result path          │
                                         │        discovery.device.found       │
                                         │  Redis: agent presence + pairing    │
                                         │  Postgres: agents, grants, events   │
                                         └─────────────────────────────────────┘
```

### 1.1 Agent — `apps/agent/` (new Go module)

| Package | Responsibility | Depends on |
|---|---|---|
| `cmd/cb-agent` | process lifecycle, signal handling, CLI subcommands | everything below |
| `internal/config` | `/etc/circuit-breaker/agent.toml` + state dir | — |
| `internal/enroll` | keygen, pairing code, enrollment handshake, credential persistence | config |
| `internal/link` | dial, Noise channel, framing, heartbeat, reconnect/backoff | config, enroll |
| `internal/spool` | bounded on-disk queue, oldest-dropped | config |
| `internal/capability` | gate — refuse and log any instruction outside the granted set | — |
| `internal/collect/host` | host telemetry collectors (slice 2) | capability |
| `internal/collect/probe` | monitor check execution (slice 3) | capability |
| `internal/collect/discover` | LAN discovery (slice 4) | capability |

Every collector package implements one interface:

```go
type Collector interface {
    Name() string
    Configure(json.RawMessage) error
    Ready() Readiness            // reported to the server, see §4.3
    Run(ctx context.Context) <-chan Frame
}
```

This is the seam that makes slices 2–4 additive. Adding a capability means adding a package and
registering it — `link`, `spool`, and `enroll` never change.

### 1.2 Backend

| Module | Responsibility |
|---|---|
| `app/api/agents.py` | fleet REST — list, detail, approve, reject, revoke, rename, grants |
| `app/api/ws_agents.py` | the agent link + enroll endpoints, and the UI-facing presence channel |
| `app/services/agent_enrollment.py` | pairing-code lifecycle in Redis, approval binding |
| `app/services/agent_registry.py` | agent CRUD, presence, capability grants, host linkage |
| `app/services/agent_link.py` | frame decode → validate → dispatch. **No domain logic.** |
| `app/core/agent_crypto.py` | server static key, Noise handshake, replay window |

`agent_link.py` owning no business logic is the important boundary. Host telemetry lands in
`telemetry_service`, probe results land in the monitoring engine's existing result path, and
discovery findings land in `discovery_import_service`. The agent subsystem transports and
authenticates; it does not re-implement any domain.

### 1.3 Frontend

`pages/AgentsPage.jsx`, `pages/AgentDetailPage.jsx`, `api/agents.js`, `hooks/useAgentLive.js` —
following the `MonitorsPage` / `useMonitorStream` patterns.

## 2. Identity, enrollment, and the E2E channel

### 2.1 Keys

Agent identity **is** an X25519 static keypair, generated on first run at
`/var/lib/cb-agent/device.key` (mode 0600, owned by `cb-agent`). The server holds its own
X25519 static keypair, generated at first boot and stored in the existing credential vault.
There is no separate signing key and no CA — the Noise handshake proves possession of both
statics.

The agent's **fingerprint** is the first 128 bits of SHA-256 over its static public key,
rendered as eight groups of four hex characters. It is displayed by the agent on stdout and by
the app on the approval screen, and the two must be compared by eye during approval (§2.4).

`machine_id_hash` is SHA-256 of `/etc/machine-id` (falling back to
`/var/lib/dbus/machine-id`). It is hashed rather than sent raw because the machine ID is itself
a stable fingerprintable identifier; the hash is still stable enough to match a rebuilt agent
back to the same host.

### 2.2 Channel

Noise `IK` nested inside WSS:

- The agent is the initiator and already knows the server's static key → 1-RTT.
- Mutual authentication and forward secrecy.
- The agent's own static is transmitted **encrypted**, so a passive observer cannot enumerate
  which agents talk to an instance.
- Transport is ChaCha20-Poly1305 with Noise's strictly-increasing nonces; rekey every 15
  minutes.
- Handshakes carrying a timestamp outside ±60s are rejected with an explicit clock-skew error.

Because the Noise channel lives *inside* the WSS connection, Cloudflare, nginx, Caddy, or any
TLS-inspecting middlebox forwards ciphertext only. This is what makes the connection genuinely
end-to-end rather than merely TLS-protected.

Frames are JSON inside the encrypted channel — debuggable, no new dependency on either side.
CBOR is the documented escape hatch if telemetry volume ever justifies it.

### 2.3 Bootstrapping trust into the install command

The server generates `install-agent.sh` per instance, embedding its URL, its static public key,
its TLS SPKI pin, and per-arch binary SHA-256 digests. The app renders one of two command forms
depending on its own certificate:

**Publicly-trusted TLS** (tunnel or real domain) — TLS carries the trust:

```bash
curl -fsSL https://cb.example.com/install-agent.sh | sudo sh
```

**Self-signed** (the LAN default) — the copied text carries the integrity anchor:

```bash
curl -fsSLk https://cb.home/install-agent.sh -o /tmp/cb-agent-install.sh && \
  echo "<sha256>  /tmp/cb-agent-install.sh" | sha256sum -c && \
  sudo sh /tmp/cb-agent-install.sh
```

The hash is rendered in the app, which the user reached over an authenticated session. Every
downstream artifact — the binary, the server static key, the TLS pin — is verified from that one
value, so the transport used to fetch the script does not need to be trusted. `GET
/api/agents/install-command` returns both forms plus the current hash.

### 2.4 Enrollment sequence

1. The script installs the binary and systemd unit and writes `/etc/circuit-breaker/agent.toml`
   with the server URL, server static public key, and TLS pin.
2. On first run the agent generates its keypair and opens a **Noise-wrapped** connection to
   `WS /api/agents/enroll`. The enrollment payload is end-to-end encrypted from the first byte;
   it is never plaintext-over-TLS.
3. The agent reports `{device_pk, hostname, machine_id_hash, os, os_version, arch,
   agent_version, primary_macs}`.
4. The server writes an `agents` row with `status='pending'` and mints a pairing code: 60 bits
   of entropy, Crockford base32, formatted `XXXX-XXXX-XXXX`, stored **hashed** in Redis under
   `agent_pairing:{code_hash}` with a 15-minute TTL, single-use. It returns the code and a
   magic link (`/agents/enroll?c=<code>`).
5. The agent prints the code, the link, and its fingerprint to stdout and the journal, then
   holds the connection awaiting approval.
6. The user approves in-app (see §5.2). The server sets `status='active'`, records the
   approving user in `agent_events`, applies the default capability grant, and the agent
   transitions into the link loop.

**Default capability grant:** `host_telemetry` enabled, `remote_probe` and `local_discovery`
disabled. Anything beyond reporting on the agent's own machine is an explicit, per-agent
decision. The approval screen pre-selects this default and allows changing it before approving.
In slice 1 the grants exist in the model with no collector behind them; they gate real behavior
from slice 2 onward.

**The pairing code is a selector, not a credential.** Both approval routes require an
authenticated session with a role permitted to approve agents, so a leaked code buys an
attacker nothing without a CB login. Codes are rate-limited per-IP and globally, with lockout
after repeated misses.

**Fingerprint comparison is the anti-race control.** The approval screen shows the device-key
fingerprint the agent printed. Without it, an attacker who enrolls a rogue agent at the right
moment could have an admin approve the wrong pending row.

**Code re-minting.** The agent requests a fresh code when the TTL lapses and prints the new
one. A user who starts an install and gets pulled away does not return to a dead code and a
reinstall.

### 2.5 Revocation and rotation

- **Revoke** flips the row to `revoked` and closes the live socket. It is instant because the
  agent holds a persistent connection. Subsequent handshakes from that static key are refused.
- **Device key rotation** happens over an established channel: the agent presents a new static
  signed by the old. This is also the re-enrollment path after a host rebuild.
- **Server static key rotation** is advertised to connected agents as a successor key, with a
  pinning overlap window during which agents accept either. Without this, losing the server key
  bricks the entire fleet.

### 2.6 Threat model — out of scope

Stated explicitly so these are decisions rather than oversights:

- A **compromised CB server** can command agents within their granted capabilities. Grants bound
  the blast radius; they do not eliminate it.
- **Root on the agent host** owns the device key. Nothing defends against this.
- **Denial of service** against the enrollment endpoint is mitigated by rate limiting only.

## 3. Data model and backend surface

### 3.1 Tables

```text
agents
  id, name, device_pk (unique), fingerprint (indexed)
  status            pending | active | revoked | rejected
  hostname, machine_id_hash, os, os_version, arch, agent_version
  primary_macs JSONB, reported_ip
  hardware_id  FK hardware  ON DELETE SET NULL   -- optional host link
  tenant_id    FK tenants   ON DELETE SET NULL
  enrolled_at, approved_at, approved_by_user_id
  revoked_at, revoked_by_user_id, revoke_reason
  last_seen_at, connected_since, notes, created_at, updated_at

agent_capability_grants                UNIQUE (agent_id, capability)
  id, agent_id FK, capability (host_telemetry | remote_probe | local_discovery)
  enabled, config JSONB, granted_by_user_id, granted_at

agent_events                           INDEX (agent_id, created_at)
  id, agent_id FK, event_type, actor_user_id, detail JSONB, created_at
  -- enrolled | approved | rejected | connected | disconnected | revoked
  -- capability_changed | key_rotated | version_changed | capability_violation
```

Slice 3 adds one column: `monitor_items.probe_agent_id` (nullable FK to `agents`) — "run this
check from this agent instead of from the server."

> **Migration convention:** these tables require `0001_init` metadata-bootstrap exclusion-list
> updates; verify with a fresh-volume mono boot.

### 3.2 Presence

Two-tier, mirroring `telemetry_cache`:

- **Redis** `agent:presence:{id}` → `{connected_at, worker}`, 60-second TTL refreshed on each
  20-second heartbeat (§4.5), so the key expires on the same three-missed-beat boundary the
  link loop uses. Authoritative and instant.
- **Postgres** `agents.last_seen_at`, written on a ~60s throttle so a 200-agent fleet does not
  generate 200 writes per heartbeat interval.

On backend restart the Redis keys expire and agents reconnect within their backoff window, so
there are no stale-online ghosts.

### 3.3 Host linkage

On enrollment the server proposes a `Hardware` match in descending confidence order:
`machine_id_hash` → MAC address → hostname. The approval screen presents it pre-filled and
overridable, including "create a new Hardware record" and "leave unlinked".

Once linked with `host_telemetry` granted, samples flow through the existing `telemetry_service`
with `source='agent'`, so live metrics, rollups, and the topology map light up with no new write
path.

### 3.4 Protocol v1 frame types

| Direction | Types |
|---|---|
| agent → server | `hello`, `heartbeat`, `telemetry.host`, `probe.result`, `discovery.finding`, `capability.violation`, `log` |
| server → agent | `hello.ack`, `capabilities.set`, `probe.assign`, `discovery.request`, `key.rotate`, `update`, `disconnect`, `ping` |

Envelope: `{v, type, seq, ts, payload}`. `agent_link.py` maps type → handler, and each handler
publishes onto a subject that already exists (`TELEMETRY_INGEST`, the monitor result path,
`DISCOVERY_DEVICE_FOUND`).

A frame whose type is not covered by an active grant is dropped server-side and recorded as
`capability_violation`. **The server enforces grants independently of the agent's own gate** —
both ends check, so a tampered agent gains nothing.

### 3.5 REST surface

`/api/agents`, using the existing `viewer / editor / admin` hierarchy:

| Endpoint | Role |
|---|---|
| `GET /` · `GET /{id}` · `GET /{id}/events` · `GET /pending` | viewer |
| `PATCH /{id}` (name, notes, host link) | editor |
| `POST /pairing/lookup` · `POST /{id}/approve` · `POST /{id}/reject` · `POST /{id}/revoke` · `PUT /{id}/capabilities` · `DELETE /{id}` · `POST /{id}/update` | admin |
| `GET /install-command` | admin |

`POST /pairing/lookup` takes a pasted pairing code and resolves it to a pending agent summary.
It is deliberately *not* named `enroll/…` so it is never confused with the agent-facing
enrollment socket below — one is a session-authenticated human action, the other is an
unauthenticated machine endpoint.

The two agent-facing WebSocket endpoints — `WS /api/agents/enroll` and `WS /api/agents/link` —
bypass session authentication entirely. The Noise handshake **is** their authentication. They
are rate-limited independently of the session-authenticated routes.

A third WebSocket endpoint, `WS /api/agents/stream`, carries presence and enrollment events to
authenticated UI clients. It is a normal session-authenticated channel and is entirely separate
from the agent link socket.

## 4. Agent internals

### 4.1 Layout and privilege

| Path | Contents |
|---|---|
| `/usr/local/bin/cb-agent` | the binary |
| `/etc/circuit-breaker/agent.toml` | server URL, server static pk, TLS pin, log level, spool cap |
| `/var/lib/cb-agent/` | `device.key`, `grants.json`, `spool/`, previous binary for rollback |

Runs as a dedicated `cb-agent` user under a hardened unit: `NoNewPrivileges`,
`ProtectSystem=strict`, `ProtectHome`, `PrivateTmp`, `RestrictAddressFamilies`,
`SystemCallFilter=@system-service`, `ReadWritePaths=/var/lib/cb-agent`.

**No `CAP_NET_RAW`.** ICMP uses unprivileged datagram sockets; the installer sets
`net.ipv4.ping_group_range` to include the agent's gid.

### 4.2 Capabilities are never host-editable

Grants arrive over the link and are cached to `/var/lib/cb-agent/grants.json` solely so a
restart while disconnected does not go dark. The server re-sends the authoritative set on every
`hello.ack` and the cache is overwritten. Nothing about what the agent may do is editable on
the host — the in-app, backend-driven configuration principle is enforced structurally rather
than by convention.

### 4.3 Capability readiness

Some collectors cannot run for environmental reasons: no `docker` group membership, `hidepid`
mounted on `/proc`, no `hwmon` sensors. Rather than failing silently, each collector reports a
`Readiness` in `hello`, and the app displays the truthful state alongside its remediation —
the same pattern as `services/discovery_readiness.py`.

```go
type Readiness struct {
    Collector   string   // e.g. "host.docker"
    State       string   // ready | degraded | unavailable
    Reason      string   // human-readable, shown in the UI
    Remediation string   // what would fix it, shown in the UI
    Missing     []string // specific probes/paths/groups unavailable
}
```

The installer runs as root and provisions everything it can at install time: creates the user,
joins the `docker` group if Docker is present, sets the sysctl. Gaps are therefore rare, and
remediation is re-running the installer from the app's copy button — still an in-app action.

### 4.4 Spool

`/var/lib/cb-agent/spool/` holds append-only segments, 64 MB default cap, oldest segment
dropped when full.

- **Only data frames spool.** Control frames never do — replaying a stale `probe.assign` is
  worse than losing it.
- On reconnect the spool drains oldest-first, **interleaved** with live traffic at a default
  ratio of one spooled frame per four live frames, so a long outage does not stall current
  telemetry behind a backlog. The ratio is a compile-time constant, not user-configurable.
- Every frame carries its original timestamp, so recovered data lands in the correct time bucket
  rather than bunching at the reconnect moment.

### 4.5 Connection loop

WebSocket ping/pong plus an application heartbeat every 20s. The server declares an agent dead
after three misses, though TCP close catches most disconnects instantly. Reconnect is
exponential backoff with jitter, 1s → 5m cap.

### 4.6 Self-update

Included in slice 1: version skew across a downloadable fleet gets painful quickly, and the
Noise channel already provides an authenticated distribution path, so no separate release
signing key is needed.

1. The agent reports its version in `hello`; the UI shows which agents are behind.
2. An admin triggers the update; the server sends the target version and SHA-256 over the
   encrypted channel.
3. The agent downloads from the instance, verifies the digest, swaps the binary, and re-execs.
4. The previous binary is retained. **If the new binary fails to re-establish a link within two
   minutes, the agent rolls back automatically.**

### 4.7 Agent CLI

In the spirit of the existing `cb` script:

| Command | Behavior |
|---|---|
| `cb-agent status` | link state, grants, collector readiness, spool depth |
| `cb-agent enroll` | re-print the pairing code, link, and fingerprint |
| `cb-agent version` | version and fingerprint |
| `cb-agent uninstall` | notify the server so the row flips cleanly, then remove unit, binary, state |

An in-app revoke stops the agent and marks it deactivated, but does **not** self-delete the
binary — it is the user's machine.

## 5. Frontend

### 5.1 Agents list

Its own top-level **Agents** nav item beside Monitors and Discovery — this is operational, not
a setting.

`AgentsPage.jsx` follows the MonitorsPage patterns: live status dot (online / offline / pending
/ revoked), name, linked host, OS and arch, version, capability chips, last seen. Filters on
status, capability, and online state. **Pending enrollments pin to the top as an
action-required banner** — an agent waiting for approval is never something the user has to go
looking for.

### 5.2 Add-agent flow

The button opens a modal that detects the instance URL and certificate mode, renders the
appropriate command form (§2.3) with a copy button, and then shows a live "waiting for
agents…" panel.

**The primary path requires no code entry at all.** The user pastes into a terminal, and the
pending agent appears in that panel the moment it enrolls. Compare the fingerprint the agent
printed against the one on screen, click approve, done.

The pairing code and magic link exist for when the browser and terminal are not side by side —
a headless box, a colleague's machine, a phone. The magic link lands on the frontend route
`/agents/enroll?c=<code>`, which resolves the code through `POST /api/agents/pairing/lookup`;
pasting the code into the modal hits the same endpoint. All three routes converge on the same
approval screen: reported facts, device-key fingerprint, proposed `Hardware` match (pre-filled,
overridable), and capability toggles pre-set to the default grant (§2.4).

### 5.3 Live status

`useAgentLive.js` subscribes to `WS /api/agents/stream`. Presence transitions push immediately,
so pending → active → online happens in place with no refresh. This is the requirement that
made transport A the only viable option.

### 5.4 Agent detail

`AgentDetailPage.jsx`: live header (status, fingerprint, version with update button, host
link), then

- **Capabilities** — toggles, each showing collector readiness warnings inline
- **Events** — timeline from `agent_events`, same component shape as the monitor event log
- **Telemetry preview** (slice 2), **Assigned probes** (slice 3), **Discovery scope** (slice 4)

Revoke is a destructive confirmation with an optional reason; the actor is recorded.

## 6. Error handling

| Failure | Behavior |
|---|---|
| Server unreachable | Agent backs off and spools. UI shows offline plus last-seen; on reconnect the spool depth is visible so catch-up progress is legible. |
| Approval never comes | Agent holds, re-mints the code every 15 min, stays `pending`. Pending rows auto-expire after 7 days. |
| Revoked while connected | Handshake refused, live socket closed, agent stops collecting and reports deactivated. |
| Bad or expired pairing code | Rate-limited with lockout after repeated misses; the message states that the agent will print a fresh code automatically. |
| Ungranted frame arrives | Dropped server-side, logged as `capability_violation`, surfaced on the agent's event timeline. |
| Update breaks the agent | No link within 2 minutes → automatic rollback to the previous binary. |
| Clock skew | Handshakes outside ±60s rejected with an explicit skew error, not a generic auth failure. |
| Duplicate `machine_id_hash` | Enrollment still succeeds as a distinct agent; the approval screen warns that another agent reports the same machine identity. |

## 7. Testing

**Go side.** Unit tests for the Noise handshake against known vectors; spool wraparound,
drain-interleaving, and segment recovery after an unclean shutdown; capability-gate refusals;
backoff timing; update rollback on link failure.

**Python side.** pytest coverage for the enrollment lifecycle, pairing-code brute-force limits,
grant enforcement, frame dispatch, and revocation closing live sockets — using the existing
SAVEPOINT-rollback fixtures. Audit assertions must account for the `log_worker_audit` isolation
behavior (it bypasses SAVEPOINT rollback; never use real production keys as `entity_name`).

**Cross-language conformance.** A fixture corpus of protocol v1 frames encoded by the Go side
and decoded by the Python side, and the reverse, run in both test suites. Protocol drift between
the two implementations is the most likely silent failure in this design, so it gets its own
gate.

**End-to-end.** A docker-compose harness that enrolls a real agent container against a real
backend and asserts the full path from copy-command to online-in-UI, including revocation
closing the socket.

## 8. Implementation slices

Each slice ends at something demonstrable.

**Slice 1 — Foundation.** Go module skeleton and CLI; `internal/config`, `enroll`, `link`,
`spool`, `capability`; Noise channel both sides; `agents` / `agent_capability_grants` /
`agent_events` tables and migration; `agents.py`, `ws_agents.py`, `agent_enrollment.py`,
`agent_registry.py`, `agent_link.py`, `agent_crypto.py`; install-script generation and binary
serving; self-update; `AgentsPage`, `AgentDetailPage`, `useAgentLive`; packaging for linux
amd64/arm64.
*Ends with:* the user copies a command, runs it, approves in-app, and the agent shows online —
reporting nothing but heartbeats.

**Slice 2 — Host telemetry.** `internal/collect/host` collectors and readiness reporting;
`telemetry.host` dispatch into `telemetry_service` with `source='agent'`; Hardware-link
proposal and confirmation; telemetry preview in agent detail.

**Slice 3 — Remote probe.** `internal/collect/probe`; `monitor_items.probe_agent_id`;
`probe.assign` / `probe.result` flow into the native monitoring engine's result path; probe
assignment UI on both the monitor and the agent.

**Slice 4 — Local discovery.** `internal/collect/discover`; `discovery.request` /
`discovery.finding` into `discovery_import_service` and the reconciler; discovery-scope
configuration per agent.

## 9. Open items for slice planning

- Exact host-telemetry metric set and sample interval defaults (slice 2)
- Whether remote-probe agents participate in the monitor scheduler's fair-share logic or run
  their own local schedule (slice 3)
- Discovery scope representation — explicit CIDR list versus agent-reported local subnets
  (slice 4)
- macOS and Windows agent support: deliberately out of scope for v1, but the Go choice and the
  `Collector` interface are what keep the door open
