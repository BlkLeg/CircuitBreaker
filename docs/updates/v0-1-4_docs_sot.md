# Circuit Breaker v0.1.4 — Documentation Source of Truth (SOT)

**Date:** March 3, 2026  
**Applies to release:** v0.1.4 (March 4 release)  
**Purpose:** Canonical topic plan for all documentation updates and new guides required for release readiness.

---

## Scope and Rules

- This file is the single source of truth for release documentation scope.
- Any guide not listed here is out of scope for v0.1.4 release readiness.
- Every P0/P1 topic must include:
  - current behavior validated against code/tests,
  - explicit audience and use case,
  - security/operational caveats,
  - links from navigation and/or parent docs.

## Product Policy Decisions for This Release

- **Auto-Discovery status:** Beta/Experimental (documented, user-visible, caution-labeled).
- **Audit log contract:** Mutable by admins (clear-all capability is documented).
- **Deployment baseline in docs:** Lab-friendly defaults first, hardening guidance second.

---

## Ownership Model

- **Product Docs Owner:** User-facing workflows, screenshots, information architecture.
- **Backend Owner:** API behavior, constraints, admin actions, retention/purge semantics.
- **Frontend Owner:** UI labels, page behavior, settings interactions.
- **Platform/SRE Owner:** Install, Docker, exposure model, auth/token/env var guidance.
- **Security Owner:** Threat caveats, credential/token handling, audit language accuracy.

---

## Must for Release (P0/P1)

| Priority | Status | Topic / Guide Title | Type | Primary Owner | Inputs / Code Truth | Acceptance Criteria |
|---|---|---|---|---|---|---|
| P0 | Update | Welcome / Index Accuracy | Update existing (`docs/index.md`) | Product Docs | `docs/index.md`, `docs/roadmap.md`, discovery/settings pages | Remove stale “coming soon” claims for shipped areas; link to new beta docs; no contradictory future tense for existing features |
| P0 | Update | Architecture Overview Accuracy | Update existing (`docs/overview.md`) | Backend + Product Docs | `docs/overview.md`, `backend/app/main.py`, `frontend/src/App.jsx` | Architecture section reflects current modules/routes, auth bootstrap, and major feature domains |
| P0 | Update | Roadmap Re-baseline | Update existing (`docs/roadmap.md`) | Product + Engineering Lead | `docs/roadmap.md`, shipped features in code/tests | Move shipped items out of “future”; distinguish beta features from true roadmap |
| P0 | Create | Release Notes: v0.1.4 | New (`docs/updates/v0-1-4_release.md`) | Product Docs | `VERSION`, merged features, release diffs | Release notes exist, map to real shipped functionality, include upgrade/behavior caveats |
| P0 | Create | Auto-Discovery User Guide (Beta) | New (`docs/discovery.md`) | Backend + Frontend | `backend/app/api/discovery.py`, `backend/app/core/scheduler.py`, `frontend/src/pages/DiscoveryPage.jsx`, `backend/tests/test_discovery.py` | Covers profiles/scans/merge/schedule/retention, clearly marked beta, includes safety and permissions caveats |
| P0 | Create | Settings & System Administration Reference | New (`docs/settings.md`) | Frontend + Backend | `frontend/src/pages/SettingsPage.jsx`, `frontend/src/pages/settings/DiscoverySettingsPage.jsx`, `backend/app/api/admin.py` | Covers timezone/language/branding/map defaults/discovery settings/admin actions with warning blocks for destructive operations |
| P0 | Create | Deployment Security Baseline (Lab + Hardened) | New (`docs/deployment-security.md`) | Platform/SRE + Security | `README.md`, `docker/docker-compose.yml`, `docker/docker-compose.prebuilt.yml`, `install.sh` | Explicit lab default posture, explicit hardening path (bind/auth/token/env); no contradictory exposure guidance |
| P0 | Update | Audit Log Guarantees and Limits | Update existing (`docs/audit-log.md`) | Security + Backend | `docs/audit-log.md`, `backend/app/api/logs.py`, `backend/tests/test_audit_log.py` | Remove append-only/delete-impossible claim; document admin clear behavior and implications |
| P0 | Update | README Documentation Links and Install Reality | Update existing (`README.md`) | Product Docs + Platform | `README.md`, docs paths, install behavior | Fix broken/mismatched links and ensure install/deploy sections match actual scripts/compose |
| P1 | Update | Contributor Policy and Branch Truth | Update existing (`CONTRIBUTING.md`) | Engineering Lead | `CONTRIBUTING.md`, workflow files, current branch strategy | Remove placeholders, confirm canonical branch and PR flow |
| P1 | Update | Security Reporting and Contact Path | Update existing (`SECURITY.md`) | Security Owner | `SECURITY.md` | Replace placeholders with actionable reporting policy and expected response process |
| P1 | Create | Backup / Restore / Clear Lab Guide | New (`docs/backup-restore.md`) | Backend + Platform | `backend/app/api/admin.py`, UI admin actions | Documents export/import/reset flows, prerequisites, and irreversible actions |

---

## Post-Release (P2)

| Priority | Topic / Guide Title | Type | Primary Owner | Inputs / Code Truth | Exit Criteria |
|---|---|---|---|---|---|
| P2 | External and Cloud Nodes Guide | New (`docs/external-nodes.md`) | Product + Backend | `frontend/src/pages/ExternalNodesPage.jsx`, API client/routes | Covers provider/kind, linking patterns, operational caveats |
| P2 | Hardware Clusters Guide | New (`docs/clusters.md`) | Product + Backend | cluster routes/models/tests | Describes cluster membership model and topology implications |
| P2 | In-App Documentation Attachments Guide | New (`docs/entity-docs.md`) | Product + Backend | `backend/app/api/docs.py`, UI docs surfaces | Covers attach/import/export/images/backlinks |
| P2 | API Capability Matrix by Domain | New (`docs/api-capability-matrix.md`) | Backend | main/api modules | Consolidated endpoint matrix for operators/integrators |
| P2 | Discovery Operations Runbook | New (`docs/discovery-runbook.md`) | Platform + Backend | discovery scheduler/retention internals | Operational playbook for scheduling, retention, troubleshooting |

---

## Release Execution Sequence

1. Land all P0 updates/creates listed above.
2. Validate docs navigation and link integrity.
3. Perform cross-check: each P0 topic references at least one code or test source.
4. Freeze wording for release notes + security posture statements.
5. Merge P1 policy updates before release announcement.

## Definition of Done (Release Docs)

- All P0 topics are merged and linked from nav/entry points.
- No broken docs links in README or docs navigation.
- No contradictions between docs and current behavior for:
  - discovery status,
  - audit log mutability,
  - deployment exposure/auth defaults.
- Release notes for v0.1.4 are present in `docs/updates/`.

## Open Questions (Must Resolve Before Final Wording Freeze)

- Confirm canonical contributor base branch (`dev` vs `develop`) for public guidance.
- Confirm final security contact channel and SLA language.
- Confirm whether any v0.1.4 features remain hidden/undocumented by policy.
