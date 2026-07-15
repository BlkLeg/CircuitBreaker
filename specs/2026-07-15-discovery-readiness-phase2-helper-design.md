# Discovery Readiness Phase 2 — `cb-helperd` Privileged Broker & Self-Healing — Design

**Date:** 2026-07-15
**Status:** Approved for planning
**Author:** Shawnji (with Claude)

## Problem

Phase 1 (`specs/2026-07-14-discovery-readiness-capability-broker-design.md`,
`plans/2026-07-14-discovery-readiness-phase1.md`) shipped readiness
detection, fail-loud scan gating, and Class-1 auto-provisioning
(nmap install + `CAP_NET_RAW`) on every deploy path. That fixed the two paths
that already run with sufficient privilege before dropping to the
unprivileged `breaker` user: bare-metal systemd and container build/entrypoint.

One capability class remains unreachable from inside the app: **LAN
adjacency** (`arp_l2`, `lan_adjacency`). Docker's `network_mode` is fixed at
container-create time from the host — nothing inside the container can
change its own network mode. This requires a privileged host helper, per the
original design's "Class 2" split.

Separately, Phase 1 only *detects* capability drift — it does not repair it.
If `nmap` is removed post-install (unrelated package cleanup, image rebuild
without cache, etc.), the readiness service reports the regression but
nothing acts on it until a human notices and re-runs the installer.

## Goals

- Ship the Class-2 broker (`cb-helperd`) described in the Phase 1 spec: a
  minimal, audited, allowlisted root daemon that performs the one class of
  action nothing else in the system can perform (network-mode changes) plus
  runtime repair of Class-1 drift.
- **Self-healing as a first-class property, not just detection.** Per the
  explicit design goal established this session: *the helper does what the
  app cannot do to itself, and the user should almost never have to interact
  with it directly.* Detection without repair is only half the job.
- Preserve the project's security posture: allowlist-only actions, no
  arbitrary exec, `SO_PEERCRED` auth, full audit trail, minimal attack
  surface on the one root-privileged process in the system.

## Non-goals

- The in-app Readiness panel / LAN-discovery toggle UI — that's Phase 3.
- Passive discovery (scapy/tshark) — out of scope per the Phase 1 spec,
  unchanged here.
- Docker Desktop host-networking support — structurally impossible (VM
  boundary), reported as `unavailable-on-platform`, not fixed.

## Architecture

`cb-helperd` runs as **root on the host**, always outside any container, and
is installed by both deploy paths' installers. The backend — containerized
or bare-metal — talks to it over a Unix domain socket.

```
Backend (uid 1000 "breaker", container or bare-metal)
   │
   │  discovery_reconciler.py (asyncio background task,
   │  job_lock.py singleton, runs at startup + every ~15 min)
   │
   │  helper_client.py — length-prefixed JSON request/response
   ▼
/run/circuitbreaker/helper.sock
   (mode 0660; SO_PEERCRED checked against the numeric uid recorded in
    /etc/circuitbreaker/helper.conf at install time)
   ▼
cb_helperd.py — root, systemd-managed, Python stdlib-only, fixed
allowlist:
   ├─ get_host_readiness        — host-side view (docker network mode,
   │                              nmap caps, host LAN interfaces)
   ├─ ensure_nmap                — install nmap via apt/dnf/pacman if missing
   ├─ grant_nmap_caps            — setcap cap_net_raw+eip on the nmap binary
   ├─ enable_lan_discovery       — generate docker-compose.lan-discovery.yml
   │                              override, snapshot current state, recreate,
   │                              health-check, auto-rollback on failure
   └─ disable_lan_discovery      — inverse of the above
```

Component boundaries, matching the Phase 1 spec's convention: **capability
model = the contract · reconciler decides when to act · helper acts ·
backend audits.**

### Why the daemon stays passive

`cb_helperd.py` has no scheduling logic, no persisted desired-state, and no
DB access. It is a pure request/response executor of the fixed allowlist.
All "when to act" logic (drift detection, retry cadence, backoff,
desired-vs-actual convergence) lives in the backend's
`discovery_reconciler.py`. This keeps the one root-privileged process in the
system as small and auditable as possible — every line of `cb_helperd.py`
should be reviewable in one sitting.

### Language and dependency isolation

`cb_helperd.py` is **Python, stdlib-only** (`socket`, `subprocess`, `json`,
no third-party packages), run without a venv, isolated from the backend's
dependency tree. A supply-chain issue in a backend dependency (FastAPI,
SQLAlchemy, etc.) cannot reach the root daemon, and there is no venv to keep
patched for this one file.

### Docker-path socket exposure

The base `docker-compose.yml` gets an unconditional bind mount
(`/run/circuitbreaker:/run/circuitbreaker`). This is harmless on any install
where `cb-helperd` isn't present (the socket simply doesn't exist, and
`helper_client` degrades gracefully — see below) and required for the
helper path to function at all once the daemon is installed.

### Compose override mechanics

Follows the existing pattern already used for the (unrelated, read-only)
Docker-socket-proxy feature — `docker/docker-compose.socket.yml`, applied via
`docker compose -f docker-compose.yml -f <override>.yml` (see
`install.sh:228-270`). `enable_lan_discovery` generates
`docker-compose.lan-discovery.yml` in the install directory
(`network_mode: host` + `cap_add: [NET_RAW]`), snapshots the current compose
state, runs `docker compose -f docker-compose.yml -f
docker-compose.lan-discovery.yml up -d`, and health-checks the recreated
container against its own `/api/v1/health`. On failure: delete the override,
recreate from the snapshot, report why. `disable_lan_discovery` is the
inverse (delete override, recreate).

### Auth detail

`SO_PEERCRED` is checked against a **numeric uid**, not a host group name —
a Docker-only install has no reason for a `breaker` *host* group to exist,
only the container-internal uid 1000. Both deploy paths resolve to uid 1000
today (no Docker userns-remap in use anywhere in this project); if
userns-remap were ever introduced this check would need revisiting — that is
a documented limitation, not handled by this design.

## Self-healing reconciliation loop

New backend module `apps/backend/src/app/services/discovery_reconciler.py`.
This is the component that makes Phase 2 actually self-healing rather than
just "detection plus a Fix button."

- **Trigger:** backend startup, then every ~15 minutes. Guarded by the
  existing `core/job_lock.py` Postgres advisory-lock pattern (same mechanism
  the continuous-polling-engine design uses for its scheduler singleton) so
  exactly one backend process runs reconciliation even with multiple
  replicas. This is deliberately *not* the full NATS/JetStream polling
  pipeline from that design — reconciliation is a cheap, idempotent recheck
  of a handful of capabilities, not a telemetry stream, and does not warrant
  that infrastructure.

- **Class 1 (`nmap_present`, `nmap_raw`) — always auto-healed, no user
  consent required.** These capabilities should simply always be true, per
  Phase 1's own Class-1 philosophy — Phase 1 just didn't re-check them after
  the first provisioning pass. Detected drift calls `ensure_nmap` /
  `grant_nmap_caps` through `helper_client` automatically. Every attempt
  (success or failure) is written to the audit chain, but success does not
  interrupt or notify the user beyond a passive "auto-healed N minutes ago"
  in the readiness data — no Fix button needed.

- **Class 2 (LAN discovery) — persisted desired state, continuously
  reconciled.** New setting `lan_discovery_desired: bool`, changed only by
  an explicit user action (the Phase 3 toggle; until then, unset/false).
  The reconciler converges *actual* state to *desired* state every cycle:
  if the user has opted in but the override silently reverted (host reboot,
  someone ran `docker compose up -d` without `-f`, a prior recreation
  failed transiently), the reconciler re-applies it — no repeat consent
  needed, since consent was already captured once. If desired flips to
  false, the reconciler tears the override down. This is the key gap Phase
  1's design left open: it modeled only current state and one-shot actions,
  with no memory of what the user had already approved.

- **Backoff:** a per-capability consecutive-failure counter. Normal cadence
  is ~15 minutes. After 3 consecutive failures for a given capability, its
  retry cadence drops to hourly and it surfaces as `needs-attention` in
  readiness — but the reconciler keeps quietly retrying at the slower rate
  rather than giving up outright, in case the underlying cause (e.g. a
  transient network or package-mirror issue) self-resolves. Any success
  resets both the counter and the cadence back to normal.

- **`needs-attention` is the genuine last resort** — reserved for cases the
  app cannot fix itself no matter how long it retries: no route to the
  package mirror, disk full, or Docker Desktop's structural
  host-networking limitation (which is `unavailable-on-platform`, never
  retried at all).

## Components / files

- **Create** `deploy/helper/cb_helperd.py` — the root daemon.
- **Create** `deploy/systemd/cb-helperd.service` — root systemd unit,
  pattern-matching the existing units in `deploy/systemd/`.
- **Create** `apps/backend/src/app/services/helper_client.py` — thin Unix
  socket client speaking the allowlist protocol. If the socket is absent
  (helper not installed), every helper-only capability reports
  `needs-helper-action` with a "helper not installed" reason, matching
  Phase 1's existing graceful-degradation states — no crash.
- **Create** `apps/backend/src/app/services/discovery_reconciler.py` — the
  self-healing loop described above.
- **Modify** `docker-compose.yml` — add the `/run/circuitbreaker` bind mount.
- **Modify** `install.sh` and `deploy/setup.sh` — register `cb-helperd` as a
  root systemd service, create `/run/circuitbreaker` (dir + perms), write
  `/etc/circuitbreaker/helper.conf` with the authorized uid. Both paths get
  the same daemon and protocol.
- **Modify** `apps/backend/src/app/services/discovery_readiness.py` (Phase
  1) — extend readiness output with auto-heal/reconciliation metadata
  (e.g. last-healed timestamp, current backoff cadence) where relevant.
- **Reuse without structural changes:** `core/audit_chain.py` (the backend,
  not the helper, writes the audit entry after each helper action — the
  helper has no DB access by design); `core/job_lock.py` (reconciler
  singleton); the `docker/docker-compose.socket.yml` override pattern
  (direct template for `docker-compose.lan-discovery.yml`).

## Error handling & rollback

- **Helper absent:** readiness reports helper-only capabilities as
  `needs-helper-action`; the reconciler simply has nothing to converge and
  logs nothing. No crash, no retry storm.
- **Recreation failure:** always auto-rollback to the pre-action snapshot,
  as in the Phase 1 spec's original data-flow description.
- **nmap install failure:** surfaced as a readiness error with the package
  manager's message; scans stay blocked via Phase 1's existing fail-loud
  gate; the reconciler keeps retrying per the backoff policy above.
- **Repeated reconciliation failure:** capped at hourly retries per
  capability after 3 consecutive failures (see backoff, above) — never
  fully abandoned, never allowed to hammer the host.

## Security considerations

- Broker remains **allowlist-only** — no arbitrary exec, no arbitrary
  compose content; override files are generated from fixed templates.
- `SO_PEERCRED` restricts callers to one numeric uid; socket perms (`0660`)
  provide defense in depth; no network exposure.
- Every privileged action — whether user-triggered or reconciler-triggered
  — is audited in the tamper-evident chain, with the actor recorded as
  either the requesting user or `system:reconciler`.
- The daemon's dependency-free, stdlib-only implementation keeps its own
  code surface minimal and independent of the backend's supply chain.
- Self-healing never *expands* what a user has approved — Class 2 actions
  only ever converge toward a state the user explicitly set via
  `lan_discovery_desired`; the reconciler cannot enable LAN discovery on its
  own initiative, only maintain or revert it.

## Testing strategy

- `cb_helperd.py`: unit tests with `subprocess` / `docker compose` mocked,
  matching the existing `discovery_probes.py` test style; `SO_PEERCRED`
  rejection of non-authorized uids; allowlist rejection of unknown actions.
- `helper_client.py`: unit tests against a real Unix socket test fixture
  (stdlib `socketserver`) — no need to mock the transport itself.
- `discovery_reconciler.py`: unit tests over a mocked `helper_client`
  covering Class-1 drift detection and repair, the failure-counter/backoff
  state transition (including cadence drop and recovery), and
  desired-vs-actual convergence in both toggle directions for Class 2.
- Installer: shellcheck plus a smoke test that the socket dir, systemd unit,
  and `helper.conf` are created on both paths.
- Compose override round-trip (enable → recreate → verify `network_mode:
  host` → disable → recreate → verify reverted) is a **manual, documented**
  verification step for this phase — recreating a container onto host
  networking is not safely automatable in this environment.

## Open items deferred to planning

- Exact `helper.conf` file format and how `install.sh` / `setup.sh`
  determine the authorized uid in edge cases (custom `--uid` install flags,
  if any exist).
- Whether `discovery_reconciler`'s audit entries need a distinct actor type
  (`system:reconciler`) added to the audit schema, or can reuse an existing
  system-actor convention — check `core/audit_chain.py`'s current actor
  model during planning.
- Precise readiness-response schema additions (last-healed timestamp,
  backoff cadence) — follows the project's `api-contract` conventions.
