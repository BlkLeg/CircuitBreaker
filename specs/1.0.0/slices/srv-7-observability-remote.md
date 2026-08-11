# SRV-7 — Observability and Remote Operation

**Requirements:** SRV-09, SRV-10
**Depends on:** SRV-2, SRV-3

## Primary files

- `apps/backend/src/app/api/metrics.py`, logging/middleware, worker audit and health
- Agent/API correlation paths, `deploy/` proxy/systemd/configuration
- `docs/deployment-security.md`, installation and troubleshooting docs

## Build sequence

1. Define stable metrics for requests, jobs, queues, workers, agents, monitors, notifications,
   integrations, dependencies, retention, and backups. Set label cardinality and compatibility rules.
2. Standardize structured logs with timestamp, severity, service, event code, request/job/agent
   correlation, outcome, and safe error. Propagate IDs through queues and agent dispatch.
3. Add redaction/property tests for tokens, passwords, keys, cookies, webhook bodies, URLs, and PII.
4. Build dashboards and symptom-based alerts with runbook links; validate them with injected faults.
5. Implement bounded support bundles with manifest, time range, health/config summaries, logs, versions,
   and opt-in sensitive fields; sign/checksum and redact by default.
6. Test reverse proxy/trusted headers, TLS ownership/renewal/failure, firewall ports, outbound agent
   endpoints, WebSocket URLs, secure cookies, client identity, and rate limits in every deployment.

## Verification and done

Inject representative API, worker, database, NATS, agent, TLS, and disk failures. An operator must be
alerted, correlate the path, produce a safe bundle, and follow a published recovery action. Metrics
must remain bounded and compatibility-tested; no secret may appear in logs or bundles.
