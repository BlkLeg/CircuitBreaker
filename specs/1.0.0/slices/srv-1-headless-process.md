# SRV-1 — Headless Process Boundary

**Requirement:** SRV-01
**Depends on:** RC architecture/API decisions

## Primary files

- `apps/backend/src/app/main.py`, `apps/backend/src/app/workers/main.py`
- `deploy/systemd/`, `deploy/setup.sh`, Compose/container entrypoints
- `deploy/cli/cb`, OpenAPI generation and frontend/static serving configuration

## Build sequence

1. Trace API startup for static assets, UI routes, weather/geocoding, browser session, scheduler, and
   in-process worker assumptions. Write headless startup tests before separation.
2. Define explicit commands/process roles for API and each worker. Add configuration that disables
   frontend/static serving and UI-only outbound calls without removing API authentication.
3. Keep migrations as an explicit coordinated entrypoint, not an accidental per-process startup side
   effect. Reject ambiguous process-role combinations.
4. Generate/publish OpenAPI from the production app and standardize machine error code, message,
   details, correlation ID, and retryability.
5. Add artifact tests that start API/workers headlessly and perform health, config, migration,
   backup/restore, token/user, and agent diagnostics without browser/static files.

## Verification and done

Run backend full tests, native/systemd and split-container headless smoke, and OpenAPI drift checks.
Done means removing the frontend artifact and denying UI-only egress does not prevent safe server
operation; mono behavior remains compatible and documented.
