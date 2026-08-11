# ACC-8 — Failure Injection, Portability, and Package Channels

**Requirements:** ACC-17, ACC-18, ACC-19, ACC-20
**Depends on:** ACC-2, SEC-17, SRV-3

## Build sequence

1. Inventory every supported deb/rpm/apk/Arch/AppImage/tar/container artifact. Verify name/version,
   digest/signature/provenance/SBOM, dependencies, users/permissions, install, upgrade, rollback where
   promised, uninstall, and data-retention behavior on clean supported platforms.
2. Build controllable faults for PostgreSQL, Redis, NATS, disk full/read-only, clock skew, DNS/TLS,
   packet loss/partition, storage, API/worker kill, and mass agent reconnect.
3. For each feature, assert the RC-defined reject/queue/degrade/retry behavior, readiness/metrics/logs,
   bounded retries/backpressure, operator action, and durable effect reconciliation after recovery.
4. Exercise clear-lab, wipe restore, tenant deletion if supported, agent revoke/uninstall, and bulk
   import confirmations, cancellation boundaries, backup prerequisites, idempotency, and audit.
5. Define versioned export manifests with schema/version/checksums and safe archive paths. Round-trip
   into every promised target and compare relationships, encrypted/unsupported fields, and warnings.
6. Scan installed filesystem/container contents for unexpected secrets, debug assets, or user data.

## Verification and done

Use release artifacts and production dependencies, not mocks, for final fault evidence. Done means
every package claim is installed, failure behavior matches its contract without silent loss/duplicate,
destructive actions are recoverable/audited, and user data can leave through the documented format.
