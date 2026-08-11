# EXEC-4 — Server Product Milestone

**Requirement:** EXEC-04
**Depends on:** EXEC-1 and RC architecture/compatibility decisions

## Implementation sequence

1. Establish the headless API/worker process boundary and generated API/error contract.
2. Assign every background function to one worker owner with idempotency, readiness, lag, drain, and
   mixed-mode prevention.
3. Implement health/lifecycle fault behavior, shared typed configuration validation, headless service
   accounts/tokens, and CLI administration.
4. Derive resource/deployment profiles from measured baselines and enforce bounds/backpressure.
5. Implement stable metrics/logs/correlation/redaction/support bundles and validate supported remote
   proxy/TLS/firewall/agent endpoint topologies.
6. Run native/split headless artifact journeys, multi-process duplicate/lease tests, dependency faults,
   graceful/rolling restart, CLI recovery, and observability diagnosis.

## Candidate control and done

Record API, worker, CLI, schema, and container/native versions as one compatibility set. Done requires
SRV-01 through SRV-10, browser-free routine/recovery operation, and one safe owner per background function.
