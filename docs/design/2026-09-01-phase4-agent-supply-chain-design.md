# Phase 4 — Agent supply chain and release-operations hardening

**Date:** 2026-09-01 · **Route:** `PRODUCTION_READINESS_ROUTE.md` §3 Phase 4 · **Findings:** F4, F3, F17
**Status:** design approved, not yet implemented.

This covers slices **4.1** (TLS pin-successor rotation), **4.2** (agent binary
signing) and **4.3** (chained agent authorization events).

Slices **4.4** (performance remediation) and **4.5** (promoting the perf gate to
blocking) are **not in scope and cannot start**. Both consume the Phase 2
baseline program, and §7 of the route records that the nightly Tier A/B/C job
has never run — "its first run is still pending a push", with no earlier report
carrying server-side numbers. 4.5 additionally requires four weeks of stable
baselines. They are named here so their absence is a recorded decision rather
than an oversight.

---

## 1. What is actually broken

### 1.1 F4 is broader than the route's row records

The route describes F4 as "single `TLSPin`; no pin frame in `frame.go`". Two
facts found while re-reading the checkout widen it.

**The pin is load-bearing on four paths, not one.** `cfg.TLSPin` is read once
from `/etc/circuit-breaker/agent.toml` by `config.Load` and is never written
again by any code in `apps/agent` (verified by grepping every non-test `.go`
file). It feeds:

| Site | Purpose |
|---|---|
| `internal/enroll/enroll.go:62` | enrollment websocket |
| `internal/link/link.go:433` | the `/link` websocket |
| `internal/link/link.go:990` | link re-dial |
| `internal/update/update.go:101` | **update binary download** |

The last one is what makes this a landmine rather than an inconvenience: an
agent stranded by a pin change cannot be repaired by pushing it a new binary,
because the download uses the same broken trust.

**Mode switches strand the fleet in both directions.**
`agent_install._tls_mode_and_pin` returns `("public", "")` for a `letsencrypt`
certificate and `("self_signed", <spki>)` otherwise. `tlsdial.NewDialer`
branches on empty-vs-non-empty pin: empty means standard system-CA
verification, non-empty means an exact SPKI match with chain and hostname
verification disabled. Therefore:

- **self_signed → letsencrypt:** every enrolled agent holds a stale non-empty
  pin which can never match the new leaf's SPKI. Whole fleet down.
- **letsencrypt → self_signed:** every enrolled agent holds an empty pin and
  performs standard verification, which a self-signed cert cannot pass. Whole
  fleet down.

A Let's Encrypt *renewal* is benign — the pin is empty either side, so a new
leaf changes nothing. The hazards are self-signed regeneration and mode
switches.

**Consequence for the design:** the unit of rotation is a *trust policy*
`(mode, pin)`, not a pin string. Advertising only a digest cannot express
"stop pinning and start trusting the system CA store", so it cannot fix half
the stranding cases.

### 1.2 F3 — integrity is server-asserted

`update.VerifySHA256` (`update.go:144`) is the only integrity check on a
self-update. The expected digest arrives in the `update` frame over the
Noise-encrypted link, so the check proves the binary matches *what the server
said*. A compromised server can serve any binary and the matching digest, and
every agent will install it. `packaging/circuit-breaker-release-key.asc` is the
package-repository key and is not wired to agent self-update.

Agent binaries **are** built by the existing pipeline —
`scripts/build_native_release.py:888` cross-compiles linux/amd64 and
linux/arm64 on every native build, `apps/agent/scripts/gen_manifest.py` writes
the manifest, and the result reaches `/opt/circuitbreaker/agent-binaries` via
`Dockerfile.mono:172`, `nfpm.yaml:48` and `install.sh:971`. So there is a build
step to hook signing into. It also means **`make build-from-source` produces
agent binaries locally**, which constrains the trust-root design (§3.2).

### 1.3 F17 — agent events are outside the hash chain

`agent_registry.record_event` writes an `AgentEvent` row and nothing else;
`agent_registry.py` contains zero `audit_chain` references. Meanwhile
`log_service.write_log` (`:203-222`) does the chaining: it takes the audit
advisory lock, reads the prior `log_hash`, and writes `previous_hash` +
`log_hash`. Agent approval, revocation, capability grants and update dispatch
are therefore tamper-evident nowhere.

---

## 2. Slice 4.1 — TLS trust-successor rotation

### 2.1 Approach

Mirror the Task 28 server-key rotation state machine, which is complete and
proven, and reuse its exact shape at every level:

| Server-key rotation (exists) | TLS trust rotation (new) |
|---|---|
| `key.rotate` frame, `kind="server"` | `tls.pin.rotate` frame |
| `config.ServerKeyRotation` in `server_key_rotation.json` | `config.TLSPinRotation` in `tls_pin_rotation.json` |
| `link.serverKeyCandidates()` | `tlsdial` candidate set |
| `agent_crypto.start_server_key_rotation` | `agent_tls_pin.start_tls_pin_rotation` |
| `agent_registry.broadcast_server_key_rotate` | `agent_registry.broadcast_tls_pin_rotate` |
| `ws_agents.py:681` resend on hello.ack | same, for the new frame |
| `agent_registry.record_server_key_pin` | `agent_registry.record_tls_pin` |
| `Agent.server_pk_{current,successor}_pinned_at` | `Agent.tls_pin_{current,successor}_pinned_at` |
| `GET /agents/server-key/{status,pending}` | `GET /agents/tls-pin/{status,pending}` |

### 2.2 The frame

A **new** frame type `tls.pin.rotate`, server→agent, control class.

```json
{ "mode": "self_signed" | "public", "successor_pin": "<base64 SPKI or empty>", "expiry": "<RFC3339>" }
```

Not an extra `kind` on `key.rotate`. That payload's `kind` is documented closed
over `"device"|"server"` and its field is named `successor_pk`, meaning key
material. Carrying a certificate pin there would make both fields lie, and the
`kind="device"` direction is agent→server, so the frame is already
bidirectional with per-kind semantics — a third kind would make
`agent_link._handle_key_rotate` and `link.handleKeyRotate` each need a branch
that ignores the other side's kind.

Additive on both sides. Registration required in:

- `apps/agent/internal/frame/frame.go` — the constant, `allFrameTypes`,
  `controlFrameTypes`
- `fixtures/agent_frame_corpus.json` — a fixture; `conformance_test.go:603`
  fails for any declared type with no fixture and no `pendingCorpusTypes`
  entry, which is the gate doing its job
- `apps/backend/src/app/schemas/agent_frame.py` — `TYPE_TLS_PIN_ROTATE` and a
  `TLSPinRotatePayload` model

An agent older than this change receives an unknown frame type; `runOnce`'s
switch has no arm for it and ignores it. That is the correct behavior — such an
agent has no successor mechanism to feed, and the convergence gate (§2.5) will
correctly report it as unconverged and refuse activation.

### 2.3 Agent side

**Persisted state.** `config.TLSPinRotation{Mode, SuccessorPin string; Expiry
time.Time}` in `<stateDir>/tls_pin_rotation.json`, written with the same
temp-file-then-rename durability `SaveServerKeyRotation` uses.

**`agent.toml` is never rewritten.** The state directory holds an override
layered over the config file's `tls_pin`. Rewriting `/etc/circuit-breaker/
agent.toml` would require the agent to hold write permission on a root-owned
config file it otherwise only reads, and a crash mid-write would leave the
agent with no way to dial anything.

**Trust resolution.** `tlsdial` changes from `NewDialer(pin string)` to
accepting an ordered trust policy:

```go
type Trust struct {
    Mode       string   // "self_signed" | "public"
    Pins       []string // ordered: effective first, then successor
}
```

Verification succeeds when the leaf's SPKI matches any candidate, or when
`Mode == "public"` and standard verification passes. `NewDialer` and
`NewTransport` both take `Trust`; all four dial sites resolve it through one
helper so the update-download path can never diverge from the link path. The
`HandshakeTimeout` carry-over documented in `tlsdial.go:48` must survive the
refactor — a bare `&websocket.Dialer{}` literal leaves it unbounded.

**Promotion.** When a dial succeeds against the successor, the agent promotes:
the successor becomes the effective pin, the rotation file is cleared. Until
then both are accepted, exactly as `serverKeyCandidates` keeps trusting both
server keys.

**Convergence reporting** rides the existing `hello` frame as one additive
field, `tls_pin_kind: "current" | "successor"`, set from whichever candidate
the TLS handshake actually matched. `HelloPayload`'s docstring already
guarantees this is safe: "Every field is optional so an old-shaped hello ...
still validates". This mirrors `record_server_key_pin`'s `key_kind` and needs
no new frame.

### 2.4 Backend

**Schema.** One migration, `0107_agent_tls_pin_rotation`, purely additive with
`ADD COLUMN IF NOT EXISTS` per the backward-compatibility principle:

- `app_settings`: `agent_tls_pin_successor_mode`, `agent_tls_pin_successor`,
  `agent_tls_pin_rotation_started_at`, `agent_tls_pin_rotation_overlap_expires_at`
- `agents`: `tls_pin_current_pinned_at`, `tls_pin_successor_pinned_at`

**Service.** New `app/services/agent_tls_pin.py` with
`load_tls_pin_rotation_state`, `start_tls_pin_rotation(db, cert)`,
`complete_tls_pin_rotation`, and a `TLSPinRotationState` dataclass carrying a
`rotation_active` property — same shape as
`agent_crypto.ServerKeyRotationState`. The successor's `(mode, pin)` is derived
from a staged `Certificate` row via the existing
`agent_install._tls_mode_and_pin`, so there is exactly one implementation of
"what pin does this certificate imply".

Only one rotation in flight, rejected with 409 otherwise — matching
`start_server_key_rotation`.

**Delivery.** `agent_registry.broadcast_tls_pin_rotate` mirrors
`broadcast_server_key_rotate`: push to every online `active` agent through
`publish_agent_control_frame` immediately after the rotation commits.
`ws_agents.link_stream` resends the frame on every accepted hello.ack while the
rotation is active, as the durability fallback for whatever the broadcast
misses.

**Routes**, on the agents router beside the server-key ones:
`POST /agents/tls-pin/rotate`, `GET /agents/tls-pin/status`,
`GET /agents/tls-pin/pending`. Admin only. Status returns fingerprints and
adoption buckets, never key material — matching `_rotation_status`.

### 2.5 The convergence gate

`POST /api/v1/certificates/{cert_id}/activate`
(`api/certificates.py:186`) refuses with **409** while any `active` agent has
not pinned the successor, and names the laggards in the response.

`force=true` overrides it and writes an audit entry listing the agents it is
about to strand. Stranding becomes a decision someone made and signed for
rather than an accident.

**Recovery for the forced case** is re-running the installer on the stranded
agent, documented in the runbook (§5). There is deliberately no agent-side
TOFU-recovery fallback: it would reintroduce a trust-on-first-use window that
an attacker could aim for by forcing pin failures, which is most of what the
pin exists to prevent.

**Ordering the operator follows:** stage the new certificate → start the pin
rotation → watch convergence → activate. The gate makes the wrong order fail
loudly instead of silently.

---

## 3. Slice 4.2 — Agent binary signing

### 3.1 Scheme

**Ed25519.** In Go's standard library (`crypto/ed25519`), no cgo, 64-byte
signatures. GPG is rejected: verifying it in Go means either shelling out to a
binary the agent cannot assume exists, or `x/crypto/openpgp`, which is
deprecated and unmaintained.

### 3.2 Where the trust root lives

The public key is embedded **at build time** via
`-ldflags "-X ...update.SigningPublicKey=<base64>"`. This is the only placement
that defends against the threat F3 names: a key the server delivers is a key a
compromised server can replace.

`scripts/build_native_release.py:888` cross-compiles agent binaries on every
native build, so a self-hoster running `make build-from-source` builds their
own. Enforcement therefore must not assume the official key:

- **Release pipeline:** private half in a GitHub secret
  (`AGENT_SIGNING_PRIVATE_KEY`), public half baked in. The app runtime never
  holds either half.
- **Source build with no key set:** produces a warn-mode binary. Nothing
  breaks; this is what `make build-from-source` does today.
- **Self-hoster wanting enforcement:** `make agent-signing-key` generates a
  local keypair; the build bakes in their public half and their pipeline signs
  with the private half.

This preserves the zero-lock-in principle: no operator is forced to trust a key
they do not control, and none is locked out of enforcement.

### 3.3 What is signed and how it travels

A **detached signature over the binary**, served beside it.

- `gen_manifest.py` grows a signing step producing
  `cb-agent-linux-<arch>.sig` next to each binary and recording it in
  `manifest.json`.
- `agent_update` gains `binary_signature_path()` reusing the existing
  `_SAFE_SEGMENT` path-traversal guard; a new route serves
  `GET /binary/{version}/{os_name}/{arch}.sig`, unauthenticated like the binary
  route — the signature *is* the integrity mechanism, so route auth adds
  nothing.
- The agent fetches the signature and verifies it against the embedded key
  **after** the existing SHA-256 check and **before** the swap, over the exact
  bytes it is about to execute. Direct, not transitive.

Signing the manifest instead was rejected: the agent has never seen the
manifest, so it would need a new fetch anyway, and the trust would become
sig → manifest → sha256 → bytes rather than sig → bytes.

### 3.4 Warn → enforce

`CB_AGENT_UPDATE_ENFORCE_SIGNATURE`, honored by the agent.

- **Warn** (default at the first release carrying this): a missing or invalid
  signature is logged loudly, an `update.status` frame reports it, and the
  update proceeds. This is required — agents running today have no embedded
  key, and binaries built before this change carry no `.sig`.
- **Enforce** (default one release later): a missing or invalid signature
  refuses the swap. A binary built with no embedded public key stays in warn
  mode regardless of the flag, since it has nothing to verify against; it logs
  that it is unenforced at startup so the state is visible rather than assumed.

The enforce date is announced in the release notes of the warn release, per the
route's Definition of Done.

---

## 4. Slice 4.3 — Chained agent authorization events

### Mechanism

`agent_registry.record_event` keeps writing its `AgentEvent` row unchanged —
the agent timeline UI reads that table — and **additionally** calls
`log_service.write_log` for a frozen subset. `write_log` already owns the
hashing, the advisory lock and the never-raises contract, so no chain machinery
is duplicated.

Mapping: `action=f"agent_{event_type}"`, `entity_type="agent"`,
`entity_id=agent_id`, `actor_id=actor_user_id`, `diff=detail`. `write_log`
sanitises `diff` before persisting, which matters because capability-grant
details carry configuration.

### The subset

```
enrolled, approved, rejected, revoked,
capability_changed,
key_rotation_started, key_rotated, key_rotation_rejected, key_rotation_expired,
update_queued
```

These are the literal `event_type` strings passed to `record_event`, read off
the call sites rather than inferred: the grant event is `capability_changed`
(singular, `agent_registry.py:897`) and a settled device-key rotation is
`key_rotated`, not `key_rotation_settled`. `key_rotation_rejected` is included
— a *refused* credential rotation is exactly as much an authorization decision
as an accepted one, and it is equally low-volume.

These are the decisions that change **who an agent is**, **what it may do**, or
**what code it runs**. All are low-volume and all but `enrolled` and the
rotation lifecycle are admin-initiated. This matches ledger row AGT-16's
wording: "Revoke, uninstall, scope expansion, remote-probe/discovery grants,
and update dispatch require explicit confirmation and audited actor/target/
outcome."

**Explicitly excluded:** `connected`, `disconnected`, `version_changed`,
`capability_violation`, `protocol_violation`, `host_link_changed`, spool-stat
and network-fact events. `host_link_changed` is an inventory association, not a
permission change. The rest are excluded for volume, not importance:
`audit_chain.lock_audit_chain` takes a **global** `pg_advisory_xact_lock` per
write, so every chained event serializes against every other audit write in the
instance. `protocol_violation` already needed throttling under F24 precisely
because it is high-volume; routing it through a global lock would convert a
write-amplification problem into a contention problem.

### Guard

A T0 ratchet pins the chained set, so adding a new authorization event type
forces a deliberate decision about whether it chains rather than defaulting to
silence.

---

## 5. Verification and evidence

| Tier | Assertion |
|---|---|
| T0 | `tls.pin.rotate` has a corpus fixture (`conformance_test.go`'s existing coverage gate) |
| T0 | Chained-event set ratchet |
| T0 | The release workflow actually invokes the agent signing step — a defined-but-never-called signer is the failure mode `test_encrypted_backup_contract.py` was written to catch, and the same trap applies here |
| T0 | No dial site constructs a `tlsdial` trust policy outside the shared resolver |
| T1 | Pin-candidate matching: successor accepted, unrelated pin refused, `public` mode accepts a CA-valid leaf and refuses a self-signed one |
| T1 | Rotation persistence across restart; promotion clears the rotation file |
| T1 | Activation refuses with 409 while unconverged; `force=true` succeeds and writes the audit entry |
| T1 | `verify_audit_chain` stays valid after an approve/revoke, and the entry exists with the expected action |
| T1 | Signature verification: valid accepted, tampered refused, absent refused under enforce and warned under warn |
| T2 (`apps/agent/e2e/`) | Certificate regenerated → rotation → fleet reconnects, no agent stranded |
| T2 (`apps/agent/e2e/`) | Tampered agent binary refused |

**Ledger rows this evidences:** AGT-07 (re-key, among its other clauses) and
AGT-16 (audited authorization). Both are `not_started` today. Neither closes
fully on this work alone — AGT-07 also names install, enroll, approve, revoke,
uninstall, update, failed update, rollback and server reinstall — so the rows
record what was actually exercised rather than being promoted on a narrower run
than they name. This is the same discipline §8 of the route applied to ACC-14.

**Documentation:** `docs/agent-key-rotation.md` gains a sibling section (or a
sibling document) for TLS trust rotation, including the operator ordering in
§2.5 and the stranded-agent recovery procedure. The route's Definition of Done
requires a "documented recovery runbook: compromised-agent revocation,
server-key rotation, Redis-outage behavior (F16)" before remote-agent
expansion; this adds the certificate-rotation entry to it.

---

## 6. Rollback and compatibility

All three slices are additive.

- **4.1:** an old agent ignores an unknown frame type; the convergence gate
  then correctly reports it unconverged. The migration adds nullable columns.
  Reverting the backend leaves harmless persisted state on agents.
- **4.2:** enforcement is flag-gated and defaults to warn; an unsigned binary
  and a keyless agent both keep working. Reverting drops the `.sig` files,
  which a warn-mode agent tolerates.
- **4.3:** a second write that `write_log` guarantees never raises and never
  aborts the parent transaction. Reverting stops chaining; existing chain
  entries stay valid.

Half-updated deployments: an updated server with old agents works (frames
ignored, signatures absent-and-warned); an updated agent against an old server
works (no rotation frame ever arrives, no `.sig` route means a 404 that warn
mode tolerates and enforce mode refuses — which is why enforce ships a release
later than the server-side route).

---

## 7. Order

1. **4.1** first. The route's stated reason holds: 4.2's rollout depends on
   agents surviving cert churn, and §1.1 shows a stranded agent cannot be
   repaired by pushing it a binary.
2. **4.2** second.
3. **4.3** independent of both; it can land at any point, including first if a
   small slice is wanted early.
