# Artifact Acceptance and Recovery Specification

**Status:** Draft; release-blocking

## Outcome

The exact artifacts offered to users pass a reproducible acceptance matrix covering installation,
critical journeys, upgrade, failure, and lossless recovery. Evidence is retained per RC-07.

## Whole-product journeys

| ID | Journey | Required assertions |
|---|---|---|
| ACC-01 | Fresh native install | Every supported OS/arch, least privilege, TLS, protected OOBE, service health, reboot persistence |
| ACC-02 | Fresh mono install | Empty volume, generated or fail-closed secrets, migrations, UI/API/workers, correct health/readiness |
| ACC-03 | Fresh split Compose | Dependency order, worker count, Caddy/TLS, no Docker socket by default, durable state |
| ACC-04 | OOBE and auth | First-admin race prevention, password policy, MFA/backup codes, OAuth/OIDC, logout and revocation |
| ACC-05 | RBAC and tenancy | Every resource/action/stream/export across all roles and two tenants, including IDOR attempts |
| ACC-06 | Inventory/topology | CRUD, tags/categories/attachments, graph edges/layout/drag, conflict/concurrency/reconnect, large graph |
| ACC-07 | Discovery/integrations | Profiles/schedules, nmap/SNMP/ARP/agent, review/merge/conflict/cancel/retry/unsafe CIDR; Proxmox credentials/TLS/conflicts/outage/rate limits/rotation |
| ACC-08 | Monitoring/notifications | ICMP/TCP/HTTP/DNS local+agent, history/uptime/alerts/retry; webhook delivery, DLQ, templates, redaction, SSRF, duplicate suppression |
| ACC-09 | Browser UI | Chromium/Firefox/WebKit, desktop/mobile, console clean, keyboard, empty/error/loading/stale states |
| ACC-10 | Accessibility/visual | WCAG 2.2 AA automation plus manual keyboard/focus/semantics/contrast/reduced motion; approved visual baselines |
| ACC-11 | Operations | Metrics/logs/alerts, config validation, backup timer, log rotation, support bundle |

AGT-01 through AGT-18 define the cb-agent journey. SEC-01 through SEC-18 define the security
journey. REL-21 through REL-26 define performance acceptance.

## Upgrade, backup, and restore

| ID | Requirement | Acceptance |
|---|---|---|
| ACC-12 | Upgrade from every supported prior version using each supported deployment mode and required server/agent order. | Data, configuration, agents, API compatibility, and service readiness reconcile after upgrade. |
| ACC-13 | Recover from failed/interrupted package installation and database migration. | Failure at each defined checkpoint has a documented, tested resume or rollback path with no silent partial state. |
| ACC-14 | Take a backup under active load and restore to a clean host, both same-version and after upgrade. | Row counts and key entities match; encrypted integration secrets work; uploads, audit chain, telemetry, tenant data, and agents recover and reconnect. |
| ACC-15 | Reject or recover safely from disk full, permission failure, corrupt archive, checksum mismatch, missing vault key, incompatible schema, and partial snapshot. | Automated verification reports precise cause; RPO/RTO and retention meet RC-06; mere process health is not sufficient. |

## Issue and artifact verification

| ID | Requirement | Acceptance |
|---|---|---|
| ACC-16 | Reproduce and verify fixes for GitHub #66, #68, #74, #75, #81, and #87 on clean installed artifacts. | Includes true Alembic chain, affected-version upgrades, non-empty `port_map` UI/API, ASCII-locale discovery, x86_64 and ARM64 start/restart/log checks, and upgrade through migration 0080. Evidence is attached before close/exception. |
| ACC-17 | Package every supported deb/rpm/apk/Arch/AppImage/tar/container channel with consistent checksums, signatures, SBOM, and provenance. | Clean-host install/update/uninstall tests use published candidates, not local source artifacts. |
| ACC-18 | Test DB, Redis, NATS, disk, clock, DNS/TLS, WAN, and process failures. | Behavior matches declared reject/queue/degrade/retry semantics; graceful recovery creates no duplicates or silent loss. |
| ACC-19 | Verify destructive-operation recovery. | Clear-lab, wipe restore, tenant deletion, agent revoke/uninstall, and bulk import conform to SEC-17. |
| ACC-20 | Verify export/import interoperability and user data portability. | Export is documented, integrity checked, and importable into the promised compatible target. |
| ACC-21 | Test real production migration scale. | Migration 0100+ indexes and the full 216-revision chain complete within approved downtime/resources at target fleet size. |

## Environment matrix rules

Every row states owner, manual/automated status, host/container image, architecture, database version,
browser where relevant, artifact digest, retained evidence, and release status. Pairwise reduction is
allowed only with a written rationale; each supported platform still receives a fresh-install smoke
and upgrade or explicit compatibility proof.

## Non-goals

- Source-only acceptance for a packaged release.
- “Restore succeeded” based only on processes becoming healthy.
- Closing issues because a matching patch exists without reproducing the reported environment.
