# Discovery Readiness & Capability Broker — Design

**Date:** 2026-07-14
**Status:** Approved for planning
**Author:** Shawnji (with Claude)

## Problem

Network discovery frequently returns near-zero results, and the failure is
**silent**. Investigation traced this to two root causes that have nothing to do
with nmap being "unreliable":

1. **The `nmap` binary and raw-socket privileges are missing or unreachable on
   most deploy paths.** `python-nmap` imports fine even when the `nmap` binary is
   absent (it is only a wrapper), so scans fail and return empty results with no
   surfaced error.
2. **The one working outcome is invisible to the user.** By the time a scan runs,
   it is far too late to discover that discovery was never going to work.

### Deploy-path audit (as shipped today)

| Path | `nmap` binary | Runs as | Raw-socket priv reaching nmap | On the LAN? | Result |
|------|:---:|:---:|:---:|:---:|---|
| `make dev` (native) | ❌ not installed | user (1000) | ❌ | ✅ host | Dead — no scanner |
| Docker mono (`install.sh`) | ✅ `Dockerfile.mono:89` | `breaker` 1000, `no-new-privileges` | ❌ `NET_RAW` dropped when supervisord switches to `breaker`; no ambient cap; no file-cap on nmap | ❌ bridge mode | Degraded — nmap TCP-connect only, ARP off, NAT'd off-LAN |
| Bare-metal systemd (`setup.sh`) | ✅ `setup.sh:1131` | `breaker` 1000 | ✅ `AmbientCapabilities=CAP_NET_RAW` propagates to nmap child | ✅ host | Works — the only good path |
| Arch `PKGBUILD` | ❌ not in `depends` | — | — | — | Missing dependency |

### Latent bug

`_nmap_os_capable()` (`apps/backend/src/app/services/discovery_probes.py:140`)
only checks `geteuid()==0` or a **file** capability on the nmap binary. It does
not know about **ambient** capabilities. On the one working path (bare-metal
systemd), nmap can perform raw scans via the ambient set, yet the code still
needlessly downgrades to `-sT` and strips `-O` (OS detection).

## Goals

- Discovery **just works** after install, with no terminal use by the user, on
  every deploy path — the "Windscribe" experience.
- All permission/capability changes are driven **from inside the app** (in-app
  toggles → backend → privileged broker), never by typed commands.
- Failures are **loud and explained**, surfaced before/at scan time, never a
  silent empty result.
- The design respects the project's security posture (`cap_drop ALL`,
  `no-new-privileges`, read-only rootfs, tamper-evident audit chain) — privilege
  is brokered through a narrow, audited, allowlisted root helper, never granted
  broadly.

## Non-goals

- Replacing nmap with a passive analyzer (Wireshark/tshark). Passive discovery
  is a *complement*, out of scope here, and needs the same L2 privilege.
- Supporting `network_mode: host` on Docker Desktop (structurally impossible —
  the VM boundary defeats it). Docker Desktop is handled as a
  `unavailable-on-platform` state, not a bug to fix.
- Arbitrary remote configuration of the host. The broker exposes a fixed action
  allowlist only.

## Key architectural insight: two classes of permission

The requirement "all in-app, no typing" splits cleanly:

- **Class 1 — grantable by a root context with zero user interaction**
  (installing nmap, `setcap` on nmap, placing `CAP_NET_RAW` in the ambient set).
  A root context already runs before the app drops to the unprivileged `breaker`
  user (the Docker entrypoint; the systemd install). Class 1 should simply always
  happen at startup/install. No toggle needed.

- **Class 2 — cannot be changed from inside the container** (host/LAN network
  adjacency). `network_mode` is fixed at container-create time from the host.
  Nothing inside the container can change its own network mode. This requires a
  **privileged host helper** — an unprivileged app talking to a root broker over
  a local socket (the Windscribe model).

## Architecture overview

```
                        ┌─────────────────────────────┐
   in-app toggle ──────▶│  Discovery Settings UI       │
                        │  (readiness cards + toggle)  │
                        └──────────────┬──────────────┘
                                       │ HTTP
                        ┌──────────────▼──────────────┐
                        │  Backend                     │
                        │  • discovery_readiness svc   │
                        │  • helper_client             │
                        │  • scan fail-loud integration│
                        └──────┬───────────────┬───────┘
                    Unix socket│               │ (in-container detection)
              (SO_PEERCRED)    │               │
                        ┌──────▼──────┐  ┌──────▼──────────┐
                        │ cb-helperd  │  │ nmap / scapy    │
                        │ (root, host)│  │ probes          │
                        │ allowlist   │  └─────────────────┘
                        └──────┬──────┘
                     docker compose / setcap / apt|dnf|pacman
```

Component boundaries (each independently testable):
**capability model = the contract · readiness-service detects · helper acts · UI presents · installers provision.**

## Components

### 1. Capability model (shared vocabulary)

A single enumerated set of discovery capabilities, shared verbatim by backend,
helper, and UI. No ad-hoc status strings anywhere.

| Capability | Enables | Granted by |
|---|---|---|
| `nmap_present` | Any nmap scanning at all | Auto (build/install) |
| `nmap_raw` | ICMP/SYN host discovery + OS detection | Auto (entrypoint caps) |
| `arp_l2` | scapy ARP → MAC resolution; most reliable LAN sweep | Helper (needs adjacency) |
| `lan_adjacency` | Process is on the real LAN, not a bridge | Helper (Docker recreate) / inherent (bare-metal) |

Each capability resolves to exactly one **state**:

- `ready` — working now.
- `auto-fixable` — a startup/install action will grant it; no user action.
- `needs-helper-action` — requires an in-app toggle → helper action.
- `unavailable-on-platform` — structurally impossible here (e.g. Docker Desktop
  + `arp_l2`); shown with a plain-language reason, never a fix.

Each capability also carries: a short human title, a plain-language explanation,
and a machine `reason_code`.

### 2. Class-1 auto-provisioning (invisible, every start)

Performed by the pre-existing root context; no toggle, no user interaction.

- **Docker (`docker/entrypoint-mono.sh` + `supervisord.mono.conf`):** ensure
  nmap present (baked into the image), and launch the backend/worker programs via
  a capability-preserving launcher (e.g. `setpriv --ambient-caps +net_raw
  --reuid breaker --regid breaker …`) so `CAP_NET_RAW` reaches the unprivileged
  discovery process. This is the missing piece today: the container declares
  `NET_RAW` but supervisord drops it when switching to `breaker`.
- **Bare-metal (`deploy/setup.sh` + systemd unit):** keep installing nmap
  (already at `setup.sh:1131`); add `setcap cap_net_raw+eip $(command -v nmap)`;
  keep the existing `AmbientCapabilities=CAP_NET_RAW CAP_NET_ADMIN`.
- **Detection-bug fix:** `_nmap_os_capable()` recognizes ambient capabilities
  (parse `CapAmb` from `/proc/self/status`, or probe a raw socket directly) so the
  working path stops downgrading unnecessarily.

### 3. Backend Discovery-Readiness service

New module `app/services/discovery_readiness.py`.

- Probes each capability and returns the structured capability model.
- Reuses existing probes (`_has_raw_socket_privilege`, `_arp_available`,
  `_nmap_os_capable`, presence of the `nmap` binary via `shutil.which`) plus a new
  `lan_adjacency` check (compare local interface subnets against RFC1918 vs
  docker-bridge ranges; consult the helper's host view when available).
- Exposed as `GET /api/v1/discovery/readiness`.
- Invoked at **startup** (emit loud WARN/ERROR logs for any non-`ready` state)
  and **on demand** (UI refresh, post-helper-action).

### 4. Fail-loud scan integration

The silent `return {}` paths in `discovery_probes.py` / `discovery_service.py`
become first-class scan events driven by readiness:

- **Pre-scan gate:** if `nmap_present` is false (or the requested scan types would
  be a guaranteed no-op), the job fails with a **blocking, explained** event —
  e.g. `"nmap unavailable — discovery cannot run. Enable it in Discovery
  Settings."` — instead of completing with a stray passive result.
- **Degraded warning:** usable-but-degraded states (e.g. `arp_l2` off) emit a
  non-blocking **warning** scan event so results are still collected but the user
  understands why MAC resolution is missing.
- These events use the existing `_log_scan_event` channel and surface in the scan
  job log + UI.

### 5. Privileged host helper — `cb-helperd`

A minimal root systemd service on the host, installed by the installer.

- **Transport:** root-owned Unix domain socket at `/run/circuitbreaker/helper.sock`,
  group-restricted to `breaker` (mode `0660`, group `breaker`).
- **Auth:** `SO_PEERCRED` — only the app's uid/gid may call. No network listener,
  no token in a file.
- **Fixed action allowlist — NO arbitrary exec:**
  - `get_host_readiness` — host-side view (docker network mode of the project,
    nmap caps, host LAN interfaces).
  - `ensure_nmap` — install the `nmap` package if missing (host/bare-metal).
  - `grant_nmap_caps` — `setcap cap_net_raw` on the nmap binary.
  - `enable_lan_discovery` — (Docker) write a **managed compose override**
    (`docker/compose.discovery.generated.yml`) adding `network_mode: host` + caps,
    **snapshot** current state, `docker compose up -d`, then health-check; on
    failure **auto-roll-back** to the snapshot and report why. (Bare-metal) no-op:
    already on-LAN.
  - `disable_lan_discovery` — inverse; remove the override and recreate.
- **Idempotent & safe:** every action is re-runnable; enabling snapshots before
  mutating; failed recreations self-revert.
- **Audit:** every action produces a structured result **and an entry in the
  tamper-evident audit chain** (actor, action, params, result, diff).

### 6. Backend ↔ helper client

New module `app/services/helper_client.py`.

- Speaks the allowlist protocol over the Unix socket (length-prefixed JSON
  request/response; strict schema per action).
- **Graceful degradation:** if the socket is absent (no helper installed), the
  system degrades to "detect + explain" — readiness still reports accurate states
  but marks helper-only capabilities as `needs-helper-action` with "helper not
  installed" context, rather than erroring.

### 7. In-app UX — Discovery Settings → Readiness panel

- **Readiness cards:** one per capability, green/red, plain-language status; no
  command strings ever shown.
- **"LAN discovery" toggle:** flipping it calls the backend →
  `helper_client.enable_lan_discovery` / `disable_lan_discovery`, with the
  rollback safety net; the UI shows progress and the final success/failure reason.
- **Platform-capped capabilities** (e.g. Docker Desktop + `arp_l2`) render as
  "Unavailable on this platform — here's why," never a fix to type.

### 8. Installer changes (both paths)

- `deploy/setup.sh` and `install.sh` register `cb-helperd` as a root systemd
  service, create `/run/circuitbreaker` + the socket dir/group, and wire the
  app's group access — so the broker exists before the user first opens the app.
- Add `nmap` to Arch `PKGBUILD` `depends`.

## Data flow — user enables LAN discovery (Docker, native Linux)

1. User flips "LAN discovery" in Discovery Settings.
2. Backend validates, calls `helper_client.enable_lan_discovery`.
3. `cb-helperd` snapshots the running compose state, writes the managed override
   (`network_mode: host` + caps), runs `docker compose up -d`.
4. Helper health-checks the recreated container (backend `/api/v1/health`).
   - **Pass:** report success → backend refreshes readiness (`arp_l2`,
     `lan_adjacency` → `ready`) → audit entry.
   - **Fail (e.g. Docker Desktop 502):** helper reverts to snapshot, recreates,
     reports failure with a plain-language reason → UI shows why, toggle stays off.

## Error handling & rollback

- **Helper absent:** readiness reports helper-only capabilities as
  `needs-helper-action`; no crash. Bare-metal LAN discovery needs no helper action.
- **Recreation failure:** always auto-rollback to the pre-action snapshot.
- **nmap install failure:** surfaced as a readiness error with the package
  manager's message; scans blocked with the fail-loud event.
- **Ambient-cap launcher unavailable** (`setpriv` missing): fall back to file-cap
  on nmap where `no-new-privileges` permits; otherwise report `nmap_raw` as
  `needs-helper-action`.

## Security considerations

- Broker is **allowlist-only** — no path accepts arbitrary commands or arbitrary
  compose content; the override file is generated by the helper from fixed
  templates.
- `SO_PEERCRED` restricts callers to the app uid; socket perms restrict to the
  `breaker` group; no network exposure.
- Every privileged action is **audited** in the tamper-evident chain.
- Auto-provisioned caps are the **minimum** (`CAP_NET_RAW`), scoped to the
  discovery process, not broadened container-wide beyond what already exists.

## Testing strategy

- **Capability model / readiness service:** unit tests over mocked probe results
  covering every capability × state combination, including the ambient-cap
  detection fix.
- **Fail-loud integration:** tests asserting a missing-nmap scan produces a
  blocking job event (not a silent completion), and a degraded `arp_l2` scan
  produces a warning event but still collects results.
- **Helper protocol:** unit tests for request/response schema, `SO_PEERCRED`
  rejection of non-app callers, allowlist rejection of unknown actions, and
  snapshot/rollback logic (mocked `docker compose`).
- **Installer:** shellcheck + a smoke test that the socket, group, and service
  unit are created.
- **End-to-end (native Linux Docker):** enable LAN discovery via the API, assert
  the container is recreated on host-net and `arp_l2` flips to `ready`; simulate a
  failed recreation and assert auto-rollback.

## Rollout / sequencing (for the plan phase)

The design supports incremental delivery:

1. **Readiness + fail-loud + Class-1 auto-provision + detection-bug fix** —
   immediate reliability win on the paths that already have privilege; unblocks
   `make dev` (install nmap) and makes failures loud everywhere.
2. **`cb-helperd` + helper_client + installer wiring** — the Class-2 broker.
3. **In-app Readiness panel + LAN-discovery toggle** — the full Windscribe UX.

## Open items deferred to planning

- Exact launcher mechanism for ambient caps in the mono container (`setpriv` vs a
  tiny wrapper) — validated against `no-new-privileges`.
- Managed-override file format and `docker compose` invocation details for the
  helper.
- API/response schema specifics for `GET /api/v1/discovery/readiness` (follows the
  project's `api-contract` conventions).
