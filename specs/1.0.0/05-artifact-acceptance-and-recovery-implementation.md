# Artifact Acceptance and Recovery — Sprint Implementation Slices

**Companion spec:** [05-artifact-acceptance-and-recovery.md](./05-artifact-acceptance-and-recovery.md)
**Status:** Ready for test-program planning

## Standalone slice plans

- [ACC-1 — Matrix, harness, and evidence](./slices/acc-1-matrix-harness-evidence.md)
- [ACC-2 — Fresh installation modes](./slices/acc-2-fresh-installation.md)
- [ACC-3 — Identity and core journeys](./slices/acc-3-core-journeys.md)
- [ACC-4 — Browser, accessibility, and operations](./slices/acc-4-browser-accessibility-operations.md)
- [ACC-5 — Upgrade and migration](./slices/acc-5-upgrade-migration.md)
- [ACC-6 — Backup and restore](./slices/acc-6-backup-restore.md)
- [ACC-7 — Historical issue verification](./slices/acc-7-issue-verification.md)
- [ACC-8 — Failure, portability, and packages](./slices/acc-8-failure-portability-packages.md)

## Slice ACC-1 — Matrix, harness, and evidence foundation

**Requirements:** Supports ACC-01 through ACC-21
**Depends on:** RC-02, RC-04, RC-07

- [ ] Convert support rows and journeys into a machine-readable matrix with owners and evidence IDs.
- [ ] Define immutable artifact acquisition, digest verification, environment provisioning, cleanup,
  redaction, diagnostic collection, and rerun behavior.
- [ ] Build shared assertions for version, health/readiness, migrations, process ownership, data
  persistence, logs, checksums, signatures, SBOM, and provenance.
- [ ] Establish clean-host/runner images and physical-host reservation for unsupported virtualization.

**Verification:** A harmless candidate artifact completes one sample job and produces a ledger-ready
evidence bundle that can be independently reviewed.

## Slice ACC-2 — Fresh installation modes

**Requirements:** ACC-01, ACC-02, ACC-03
**Depends on:** ACC-1, RC-02

- [ ] Test native packages on every supported OS/architecture with least privilege, TLS, OOBE,
  service startup, reboot, and uninstall behavior.
- [ ] Test mono from empty storage with secrets, migrations, UI/API/workers, and health semantics.
- [ ] Test split Compose dependency ordering, exact worker topology, Caddy/TLS, socket exclusion, and
  durable state.
- [ ] Capture installation duration, resource use, logs, file ownership, exposed ports, and leftovers.

**Verification:** All supported fresh-install rows pass using release candidates and documented steps.

## Slice ACC-3 — Identity and core product journeys

**Requirements:** ACC-04, ACC-05, ACC-06, ACC-07, ACC-08
**Depends on:** ACC-2, relevant SEC/AGT contracts

- [ ] Automate OOBE/auth, RBAC/tenancy, inventory, topology, discovery, Proxmox/integrations,
  monitoring, notifications, and webhooks as stateful journeys.
- [ ] Include conflict, cancellation, retry, unsafe-input, credential/TLS, rotation, outage, SSRF,
  duplicate suppression, reconnect, and large-graph cases.
- [ ] Reuse shared entities across journeys to prove subsystem composition.

**Verification:** Expected durable state and side effects reconcile after every journey and restart.

## Slice ACC-4 — Browser, accessibility, and operations

**Requirements:** ACC-09, ACC-10, ACC-11
**Depends on:** ACC-2, REL-17, REL-18

- [ ] Run Chromium, Firefox, and WebKit at supported desktop/mobile viewports against production builds.
- [ ] Assert routing, cookies/CSRF, real API, WebSockets, responsive behavior, and console health.
- [ ] Run WCAG automation and manual keyboard/focus/semantics/contrast/reduced-motion review.
- [ ] Approve visual baselines for critical and empty/error/loading/stale states.
- [ ] Exercise metrics, logs, alerts, configuration validation, backup timer, rotation, and bundles.

**Verification:** Browser matrix and manual accessibility checklist are retained and have no
unreviewed console or accessibility failure.

## Slice ACC-5 — Upgrade and interrupted migration

**Requirements:** ACC-12, ACC-13, ACC-21
**Depends on:** ACC-1, RC-04 compatibility matrix

- [ ] Generate realistic target-scale datasets for each minimum supported source version.
- [ ] Test prescribed server/database/agent upgrade order in every deployment mode.
- [ ] Inject interruption at package and migration checkpoints; verify resume or rollback.
- [ ] Test the true Alembic chain, migration 0100+ indexes, advisory coordination, downtime, locks,
  disk, and resource budgets.
- [ ] Reconcile data, agents, configuration, APIs, and readiness after success and recovery.

**Verification:** Every promised source-to-1.0 path and defined interruption checkpoint passes.

## Slice ACC-6 — Live backup and clean restore

**Requirements:** ACC-14, ACC-15
**Depends on:** ACC-2; RC-06 RPO/RTO targets

- [ ] Build a representative active dataset with encrypted secrets, uploads, audit, telemetry,
  tenants, agents, integrations, and queued work.
- [ ] Back up under activity and restore to clean same-version and post-upgrade hosts.
- [ ] Verify row counts, key entities, secret usability, uploads, chain validity, agent reconnection,
  and functional journeys—not only process health.
- [ ] Inject disk full, permissions, corruption, checksum mismatch, missing key, incompatible schema,
  and partial snapshot failures.
- [ ] Measure RPO/RTO and test retention/expiry.

**Verification:** Recovery meets RC-06 and every unsafe input fails with a documented recovery path.

## Slice ACC-7 — Historical issue artifact verification

**Requirements:** ACC-16 and AGT-10 through AGT-12
**Depends on:** ACC-2, ACC-5

- [ ] Create a case for each issue #66, #68, #74, #75, #81, #87, and #101 defect.
- [ ] Reproduce the original affected environment or document why an equivalent is valid.
- [ ] Run fresh and affected-version upgrades, non-empty `port_map`, minimal ASCII locale, migration
  0080, ARM64 startup/restart/image handling, PyInstaller cleanup, and environment-ID cases.
- [ ] Attach immutable evidence to each issue before closure or RC-08 exception.

**Verification:** Patch presence alone never yields pass; every issue has installed-artifact evidence.

## Slice ACC-8 — Failure, portability, and package channels

**Requirements:** ACC-17, ACC-18, ACC-19, ACC-20
**Depends on:** ACC-2, SEC-17, SRV-3

- [ ] Test every supported package/container channel for identity, signature, SBOM, provenance,
  install, update, rollback where promised, and uninstall.
- [ ] Inject DB/Redis/NATS, disk, clock, DNS/TLS, WAN, and process failures and reconcile behavior.
- [ ] Exercise destructive safeguards and recovery for all SEC-17 operations.
- [ ] Round-trip documented export/import formats into every promised compatible target.

**Verification:** No silent loss/duplicate, unsupported package claim, or unverified portability path remains.
