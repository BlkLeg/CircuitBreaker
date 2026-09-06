# Agent reachability and unattended enrollment

**Status:** design, approved 2026-09-05. Supersedes nothing; additive to Phase 4.
**Scope:** how an agent anywhere reaches a Circuit Breaker server, and how it
enrolls without a human present.

---

## 1. What is actually broken

### 1.1 The server never asks what address an agent should dial

`GET /api/v1/agents/install-command` and `GET /install-agent.sh` both derive
`server_url` from `core.forwarded.forwarded_base_url(request)` — the address the
**operator's browser** used. That value is written verbatim into the agent's
`/etc/circuit-breaker/agent.toml` as `server_url` and is the only address the
agent will ever dial.

For an agent on the same LAN this is right by accident. For an agent anywhere
else it is wrong by construction: an operator browsing `https://192.168.0.51`
gets an install command that bakes an RFC1918 address into a machine that can
never route to it. The agent then retries that address forever, and the fleet
page shows nothing at all — there is no failure to see, because the agent never
reaches the server to report one.

This is the defect that has made the agent undeployable outside the LAN since
inception. It is not a networking-layer problem; the transport is sound. It is
a missing question: *what address will this agent use to reach me?*

### 1.2 Every agent requires a human

`enroll.Run` blocks until an operator compares a fingerprint and clicks approve
(`apps/agent/internal/enroll/enroll.go:37` — "that wait is a human pressing a
button and is legitimately unbounded"). This is a genuine security property:
**no bearer secret exists anywhere in the current design**, and identity is
confirmed out-of-band by a person.

It also makes scripted deployment impossible. A cloud-init script, a launch
template, or an autoscaling group cannot click. Any fleet larger than what one
person will approve by hand is out of reach.

### 1.3 What is *not* broken, and must not be rewritten

An earlier framing of this work proposed redesigning the agent's networking and
security layers — gRPC, mutual TLS, token-to-certificate enrollment. That would
discard working, hardened subsystems. For the record, the following already
exist and this design does not touch them:

| Property | Where |
|---|---|
| Outbound-only; the agent has no listener | no `net.Listen` anywhere in `apps/agent` |
| Persistent authenticated stream, server pushes commands down it | `/api/v1/agents/link` |
| Mutual authentication and end-to-end encryption | Noise IK; `server_static_pk` pinned in `agent.toml` |
| Enrollment, fingerprint comparison, admin approval | `enroll.go`, `ws_agents.enroll_stream` |
| Server identity key rotation with overlap | `agent_crypto.load_server_key_rotation_state` |
| TLS pin rotation, convergence-gated | slice 4.1, `tls.pin.rotate` |
| Revocation | agent status `revoked` |
| Reconnect, backoff, offline spool | `internal/link`, `spool_cap_bytes` |
| Signed binaries verified before swap | slice 4.2, Ed25519 |
| Install command with `--pinnedpubkey` and `sha256sum -c` | `agent_install._INSTALL_SCRIPT_TEMPLATE` |
| CPU, load, memory, swap, disks, filesystems, per-interface network, temperatures, uptime | `frame.HostSummary` |
| Container context | `collect/host/docker.go` |

Because Noise IK runs *inside* the WebSocket, an intermediary that terminates
TLS — a tunnel, a reverse proxy — sees Noise ciphertext, not agent data, and
cannot impersonate the server without `server_static_pk`. This is what makes
§2.2's "reachability is the operator's choice" safe.

---

## 2. Decisions

### 2.1 The control plane stays outbound-only

Considered and rejected: letting the agent listen so the server dials it. For
the specific case of a closet server and a cloud agent it would work. It was
rejected because:

- It inverts which case is easy. Every agent behind NAT, on CGNAT, in a
  container, or on a network the operator does not control works today and
  would stop.
- It multiplies the address problem by N. One server address to get right
  becomes one per agent, each with its own dynamic IP and firewall rule.
- It does not remove the need for outbound. To dial an agent the server must
  know that agent's current address, which the agent must report — over an
  outbound connection. The listener is then redundant for control, since the
  server can already push down `/api/v1/agents/link`.
- It adds a listening port to every monitored host, including hosts on hostile
  networks. The systemd unit currently runs the agent under
  `NoNewPrivileges`, `ProtectSystem=strict`, `PrivateTmp` and a
  `SystemCallFilter`; a service to defend on every host is a lateral-movement
  target that Wazuh, Netdata and cloudflared all avoid by construction.
- It solves neither end of a both-ends-behind-NAT deployment.

A **local** listener — a loopback `/metrics` and health endpoint, as Netdata's
agent serves on :19999 — is a separate, defensible feature. It belongs to the
metrics work, not here, and is out of scope (§12).

### 2.2 Reachability is the operator's choice; Circuit Breaker does not build it

The agent dials one configured address. How that address comes to exist — a
public IP, a VPS, DDNS, a port forward, a reverse proxy, a Cloudflare Tunnel, a
WireGuard or Tailscale overlay — is the operator's business, documented but not
implemented here. No tunnel vendor is baked in, which keeps the zero-lock-in
and `CB_AIRGAP` principles intact.

Two facts justify not building a transport:

- **Plain WireGuard does not solve NAT traversal.** It requires at least one
  peer with a reachable endpoint. A server with no inbound path cannot complete
  a WireGuard handshake either; the hole-punching and relay layer that fixes
  that is the expensive part, and is what Tailscale/Headscale add on top.
- **A tunnel needs no agent change at all.** If cloudflared exposes
  `https://cb.example.com` and forwards to the server, an agent configured with
  that address works unmodified. Building tunnel support into the agent would
  buy nothing the endpoint setting does not already buy.

### 2.3 One address per agent, chosen at install

An agent's `agent.toml` carries a single `server_url`, as it does today. A LAN
agent gets the LAN address; a cloud agent gets the FQDN. An agent that
physically moves between networks must be reinstalled.

Rejected: a candidate list the agent tries in order. It handles hairpin NAT and
roaming laptops without operator thought, but it changes the config schema and
the connection logic for a case that reinstallation already covers. If roaming
agents become common, this is the additive change to make — `server_url` stays,
a `server_urls` list is added alongside it.

### 2.4 Unattended enrollment via short-lived tokens

Included, with eyes open. §5 states the cost plainly.

---

## 3. Data model

### 3.1 `AppSettings.agent_endpoints`

A JSON column, default `[]`, of `{"id": str, "label": str, "url": str}`.
`id` is a short random string minted when the endpoint is created and never
reused. Labels are operator-facing and mutable, so they cannot identify an
endpoint in a URL that may have been generated days earlier.

JSON rather than a table: this is a short, operator-authored list read by one
settings screen and one wizard. A table would buy ordering and foreign keys
that nothing needs. Promote it if it ever grows constraints.

An empty list means *not configured*, and the install flow then reproduces
today's `forwarded_base_url` behaviour with a visible warning. No upgrade
breaks on a field nobody has filled in.

`AppSettings.api_base_url` already exists and is the externally reachable base
URL for browser-facing links (`auth_oauth._get_app_base_url`,
`smtp_service.public_base_from_request`). It is deliberately **not** reused: the
address a browser uses and the address an agent uses can legitimately differ,
which is the entire LAN-versus-FQDN case. It is a reasonable seed for the first
endpoint the operator is offered.

URLs get a **scheme-and-host check only** — HTTP(S), non-empty host, trailing
slash stripped. Deliberately *not* `core/url_validation.py`: its
`_is_forbidden_address` rejects private addresses unless `allow_private` is set,
so it would refuse `https://192.168.0.51` — precisely the LAN endpoint an
operator most needs to declare. It also resolves DNS, which answers the wrong
question: what matters is whether the address resolves from the *agent*, and the
server cannot know that (§6).

### 3.2 `agent_enrollment_tokens`

| Column | Notes |
|---|---|
| `id` | PK |
| `token_hash` | SHA-256 of the token, unique, indexed. The token itself is never stored, mirroring `user_service._hash_token` |
| `label` | operator-facing |
| `endpoint_url` | the address this token's agents are told to dial |
| `capabilities` | JSON; the grant scope applied on auto-approval |
| `max_uses` | default `1` |
| `uses` | default `0` |
| `expires_at` | required |
| `revoked_at` | nullable |
| `created_by_user_id`, `created_at` | provenance |

`max_uses` exists because single-use tokens break the case that motivates the
feature: one token baked into a launch template, N instances booting, only the
first enrolling. Which agents came from a token is derived from
`agents.enrollment_token_id`, not stored here.

### 3.3 `agents` gains two nullable columns

- `enrolled_via_endpoint` — the URL the agent reported dialing. The server has
  no other way to know, and this is what makes a broken endpoint visible in the
  UI rather than inferred from an agent that never appears.
- `enrollment_token_id` — provenance, nullable FK. Tokens are revoked, never
  hard-deleted, so this reference stays resolvable for the life of the agent.

All migrations use `ADD COLUMN IF NOT EXISTS` and are additive, per the
backward-compatibility rule in CLAUDE.md.

---

## 4. Token lifecycle

**Mint.** `POST /api/v1/agents/enrollment-tokens`, admin only. Body: label,
endpoint id, capability scope (the same shape `POST /{agent_id}/approve`
accepts), TTL (default 1 hour, maximum 24), and `max_uses` (default 1). An hour
rather than minutes because the realistic path is a human pasting the value into
a launch template or a secrets store, not a script consuming it immediately. Returns the plaintext **once**.
Format is `cbe_` followed by 32 random bytes, base64url — the prefix exists so
secret scanners and log redaction have a stable thing to match.

**Carry.** The install script writes the token to
`/etc/circuit-breaker/enroll-token`, mode `0600`, owned by `cb-agent`. It is
supplied to the script via the `CB_ENROLL_TOKEN` environment variable or on
stdin, never as a script argument: `argv` is visible in `ps` and lands in shell
history and cloud-init logs.

**Present.** The agent includes the token in its enroll hello — that is, inside
the Noise channel. The token is never on the wire in plaintext, even to an
intermediary terminating TLS.

**Consume.** One atomic statement:

```sql
UPDATE agent_enrollment_tokens
   SET uses = uses + 1
 WHERE token_hash = :hash
   AND uses < max_uses
   AND revoked_at IS NULL
   AND expires_at > now()
RETURNING id, endpoint_url, capabilities;
```

No row returned means invalid, spent, revoked or expired — all reported to the
agent as one indistinguishable failure, so the token endpoint is not an oracle.
Concurrent boots cannot over-consume, and this is the one genuine race in the
design; §6 requires a test for it.

A consumed token creates the agent with status `active` and grant rows from the
token's capability scope, written at that moment. This is consistent with the
`agent_capabilities` invariant, which governs never silently enabling a
capability on an **already-approved** agent; here approval is what is
happening.

**Revoke.** Sets `revoked_at`; consumption checks it. Revoking does not affect
agents already enrolled through it — they hold their own device identity.

**Erase.** The agent unlinks `/etc/circuit-breaker/enroll-token` after a
successful enroll. A spent token left on disk is a stale secret with no purpose.

**Audit.** Mint, use and revoke chain into `log_service.write_log` alongside the
ten authorization events F17 already chains. These are low-volume by nature —
deliberately unlike the high-volume agent events F17's docstring warns against
chaining.

**Abuse.** The token path reuses the existing per-IP and global enrollment
rate limits in `ws_agents.enroll_stream`. It is **not** subject to the
concurrent-pending cap, and cannot be: a token-enrolled agent is never pending.
`max_uses` and the TTL are what bound a token's blast radius, which is why both
are required rather than optional.

---

## 5. What this trades away

`max_uses > 1` is a real reduction in security posture and is stated here so it
is chosen rather than discovered. A multi-use token in a launch template is a
credential that will enroll anything presenting it, for its whole TTL. Today's
design has the stronger property that **no bearer secret exists at all**.

Mitigations, none of which eliminate it: short default TTL, `max_uses` default
of 1, single-endpoint scoping, capability scoping, revocation, hashed storage,
env/stdin delivery, and audit rows for every use. The attended flow remains the
default and is unchanged; tokens are opt-in.

The second weakness: **nothing validates that a configured endpoint resolves
from where an agent will run.** The operator types an address and the system
believes them. §6 is damage limitation, not a fix.

---

## 6. Verification, and its honest limits

The server cannot verify reachability. It cannot dial the agent — there is no
listener, by §2.1 — and testing from the operator's browser proves only that
the operator's network can reach the address. **No "verified" badge appears
anywhere in this design, because the server cannot earn one.**

What exists instead:

1. **Script preflight.** Before `useradd` or any download, the install script
   requests `${CB_SERVER_URL}/api/v1/health` and, on failure, prints the
   address it could not reach and exits. Failure lands at the first step, naming the
   cause, instead of three steps later inside a binary fetch.
2. **Agent-side reporting.** The status file and logs name the address the
   agent cannot reach.
3. **Wizard feedback.** The "waiting for the machine to check in" step shows
   the chosen endpoint and, after ~90 seconds with no check-in, says what to
   verify.
4. **Fleet visibility.** Agent detail shows `enrolled_via_endpoint`; the
   endpoints settings screen shows how many agents enrolled through each. An
   endpoint with zero is a smell an operator can act on.

---

## 7. Install and UX changes

- **Settings → Agent endpoints.** CRUD over `agent_endpoints`, with validation
  and a plain statement that this is the address agents will dial.
- **Add Agent wizard** gains a first step: which endpoint, and attended or
  unattended. The endpoint is prefilled with whichever matches the current
  `Host`, else the first configured, else free text with a warning.
  - *Attended* — today's command, no token, human approves. Unchanged.
  - *Unattended* — mints a token and shows the command once, with the `argv`
    warning beside it.
- **`/install-agent.sh?endpoint=<id>`** resolves that endpoint instead of
  calling `forwarded_base_url`. An **absent** parameter falls back to
  `forwarded_base_url`, so existing commands keep working. An **unknown or
  deleted** id returns 404 naming the id, and never falls back: silently
  substituting a different address is precisely the defect §1.1 describes, and
  it would reappear the moment an operator deleted an endpoint whose install
  command was still sitting in someone's terminal. `script_sha256` is
  computed over the same rendered variant it already is; the endpoint is
  threaded through both `build_install_command` and the route.

## 8. Agent-side changes

Deliberately minimal:

- Read `/etc/circuit-breaker/enroll-token` if present; include it in the enroll
  hello; unlink on success.
- Report the dialed URL in hello so the server can record
  `enrolled_via_endpoint`.

No transport change, no new dependency, no listener, no change to `agent.toml`'s
existing keys.

---

## 9. Compatibility

Additive migrations only. `server_url` semantics unchanged. Existing agents,
existing install commands and the attended flow are unaffected. Empty
`agent_endpoints` reproduces current behaviour plus a warning. `CB_AIRGAP` is
untouched: the server makes no new outbound calls, and the agent's connection to
its own server was never an internet egress.

## 10. Testing

- Token expiry, revocation, endpoint scoping, capability scoping.
- **Concurrent consumption respects `max_uses`** — the one real race.
- Failure modes are indistinguishable to the caller (not an oracle).
- `/install-agent.sh?endpoint=` renders the selected URL, with a matching
  `script_sha256`; absent parameter falls back to `forwarded_base_url`.
- Token never appears in logs or in the rendered script.
- E2E: an unattended enrollment beside the attended scenario the harness
  already runs.
- Frontend: wizard endpoint selection, show-once token display.

## 11. Slicing

This is two independently shippable slices, and the order matters because the
first carries none of §5's cost.

**Slice A — endpoints (fixes the blocker).** `agent_endpoints`, the settings
screen, `enrolled_via_endpoint`, the wizard's endpoint step, `?endpoint=<id>`
threaded through `build_install_command` and the `/install-agent.sh` route, and
the script preflight. No tokens, no new secret, no change to the security
posture. After this slice an operator can deploy an agent to AWS from a closet
server, attended. **This alone closes §1.1**, which is the reason the agent has
been undeployable.

**Slice B — unattended enrollment.** The token table, mint/revoke endpoints,
consumption, auto-approval, the agent-side token file, and the unattended branch
of the wizard. This is where §5's trade lives, and it can be deferred or
declined without losing slice A.

Slice B depends on slice A: a token is scoped to an endpoint, which does not
exist until A ships.

## 12. Out of scope

Tunnels and overlays (documented, not built); any agent listener including the
local metrics endpoint; macOS and Windows packaging; the metrics and security
capability expansion (per-process, listening ports, package inventory, file
integrity monitoring, auth events) — that is the next spec, and it builds on
this one.
