# ACC-2 — Fresh Installation Modes

**Requirements:** ACC-01, ACC-02, ACC-03
**Depends on:** ACC-1 and RC-02

## Primary touchpoints

- `install.sh`, `uninstall.sh`, `deploy/setup.sh`, `deploy/systemd/`, `packaging/`
- `docker-compose.yml`, `docker/docker-compose.yml`, `docker/docker-compose.socket.yml`
- `docker/20-migrate.sh`, `scripts/test-mono-e2e.sh`, installation documentation

## Build sequence

1. Provision each supported native OS/architecture from a clean image/host. Install the signed package
   as documented; assert signature, users/groups, ownership, permissions, services, ports, TLS, OOBE
   protection, health/readiness, logs, and reboot persistence.
2. Start mono from empty volumes with no inherited secrets. Assert secure secret generation/fail-closed
   behavior, one migration pass, UI/API/workers, persistence, backup path, and restart behavior.
3. Start split Compose from empty volumes. Assert dependency ordering, exact worker owners, Caddy/TLS,
   no Docker socket by default, readiness, state persistence, and independent restart.
4. Test cancellation/failure at installer checkpoints, insufficient permissions, occupied ports,
   unsupported architecture, missing prerequisite, and read-only/disk-full paths.
5. Uninstall each mode and classify retained data/config/backup versus removed binaries/services.
6. Compare observed commands, paths, ports, and behavior with installation documentation.

## Verification

Use the exact candidate artifacts and production service accounts. Run `scripts/test-mono-e2e.sh` only
as supporting evidence after confirming it installs the candidate rather than rebuilding source.
Retain service journals, container inspect, package inventory, file tree metadata, and reboot results.

## Done

Every RC-02 installation row passes from a clean system, survives reboot, exposes only documented
ports, and follows a predictable uninstall/data-retention contract.
