# cb status and cb doctor — companion previews
Preserve the established terminal design, orange headings, purple metadata,
monospace aligned columns, muted evidence, green success and red failure.
No installer art on routine commands. Both are native Linux illustrative samples,
not live reads or implemented output changes. One readable screen per preview.

## STATUS — service state, no health assertion
$ cb status
Circuit Breaker 0.4.7  STATUS  native / linux-amd64
12 / 12 app units active · 1 shared service active
Service state only; run cb doctor for readiness checks.

APP SERVICES table: Unit, State, Active since. Every row active, 10:32 Sep 30.
circuitbreaker-postgres
circuitbreaker-pgbouncer
circuitbreaker-redis
circuitbreaker-nats
circuitbreaker-backend
circuitbreaker-worker@discovery
circuitbreaker-worker@notification
circuitbreaker-worker@telemetry
circuitbreaker-worker@integration
circuitbreaker-worker@monitor_scheduler
circuitbreaker-worker@monitor_poll
circuitbreaker-worker@monitor_probe_dispatch

SHARED SERVICES
nginx  active  09:14 Sep 30  (shared)

INSTALL
Identity: /etc/circuitbreaker/install-identity.json
Endpoint (configured): http://127.0.0.1:8088/api/v1/readyz
Started timestamp is shown, not labeled as elapsed uptime.
Next: cb doctor · cb logs -f · cb resources --watch
No automatic restart, no invented status --watch flag, no health-passed badge.
Sample data · design preview outside terminal.

## DOCTOR — local checks with a concrete problem
$ cb doctor
Circuit Breaker 0.4.7  DOCTOR  native / linux-amd64
8 passed · 1 failed · 1 skipped
Attention required — data filesystem below minimum free space.

CHECKS table: Result, Check, Evidence. Exactly 10 checks:
PASS Install identity Valid native identity
PASS Binary selftest Application modules load
PASS PostgreSQL service active
PASS Redis service active
PASS NATS service active
PASS Backend service active
PASS Backend readiness :8000/api/v1/readyz responds
PASS Identity endpoint :8088/api/v1/readyz responds
FAIL Data filesystem 512 MiB free; minimum 1 GiB
SKIP Admin diagnostics CB_ADMIN_TOKEN unset

NEXT STEPS
1. Inspect the data filesystem:
   df -h /var/lib/circuitbreaker
2. Review local backup retention or increase filesystem capacity.
   Retain a verified recovery copy before deleting backups.
3. Re-run: cb doctor

Authenticated checks were not requested. They are not counted as passes.
Service active is process state; readiness rows report HTTP probes separately.
No false database-connection probe (native code only checks PostgreSQL unit here),
no invented worker-heartbeat checks when authenticated diagnostics are skipped.
No env contents, credentials, setup tokens or database URLs in output.
Footer: No repairs made · Exit 1
More: cb doctor --json · cb diag bundle
Sample data · design preview outside terminal.
