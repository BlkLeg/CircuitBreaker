# AGT-1 — Composed Release Gate

**Requirements:** AGT-01, AGT-02, AGT-03, AGT-04
**Priority:** P0
**Primary files:** `apps/agent/e2e/test_agent_release_gate.py`, `test_agent_e2e.py`,
`docker-compose.yml`, `.github/workflows/`

## Build sequence

1. Run the current gate repeatedly and record duration/failure phase. Diagnose product, harness, and
   systemd-container failures separately before changing behavior.
2. Keep one continuous stateful journey: enroll/approve; telemetry; scope grant; discovery; review and
   import; create ICMP/TCP/HTTP(S)/DNS monitors against imported hardware from that agent; outage and
   spool catch-up; independent agent/backend restarts; grants; revoke; update and rollback.
3. Assert durable IDs, no duplicate hardware/monitors/samples, preserved collection timestamps,
   presence reconciliation, scope refusal, and post-revoke rejection at each transition.
4. Exercise forced rollback and production-transport malformed/oversized frames. If retained in a
   separate test, run it against the same artifact and link its evidence explicitly.
5. Resolve the uninstall xfail without weakening the production unit. Add bounded polling, seeded
   fault timing, phase timestamps, service logs, inspect output, DB state, and artifact digests.
6. Add a scheduled workflow and required RC invocation with a concurrency lock for the shared stack.

## Verification

```bash
cd apps/agent && go test -race ./... && go vet ./...
cd apps/agent/e2e && pytest -q --no-cov -p no:randomly test_agent_release_gate.py
```

Run the full gate repeatedly to the approved flake threshold. Never run two sessions against the same
Compose project. Retain diagnostics for both green and failed RC runs.

## Production constraints and done

Do not weaken agent permissions, scope validation, systemd sandboxing, TLS, or rollback confirmation
to accommodate the harness. Done means the signed candidate completes the continuous journey,
delegated cases are traceable, the xfail is gone, and release/scheduled workflows retain evidence.
