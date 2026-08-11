# ACC-3 — Identity and Core Product Journeys

**Requirements:** ACC-04, ACC-05, ACC-06, ACC-07, ACC-08
**Depends on:** ACC-2, SEC tenant/auth gates, AGT composed gate

## Objective

Prove that critical subsystems compose using shared durable entities, real API/session boundaries, and
production workers—not isolated mocks or per-feature databases.

## Journey sequence

1. Complete protected OOBE, create roles/users, enforce password/MFA/OAuth/session lifecycle, and
   prove logout/revocation across REST and streams.
2. Create two tenants only if supported; execute role/action/IDOR matrix across all shared resources.
3. Create/edit/delete hardware, compute, storage, service, network, cluster, tags, categories, and
   attachments. Build topology, persist layout/edges, reconnect, and resolve concurrent edits.
4. Configure discovery profiles/schedules; run supported nmap/SNMP/ARP/agent paths; review, merge,
   conflict, import, cancel, retry, and refuse unsafe CIDRs.
5. Configure Proxmox/integrations with valid/invalid credentials, TLS errors, partial outage, conflicts,
   rate limits, and secret rotation.
6. Create local and agent-vantage ICMP/TCP/HTTP/DNS monitors against discovered/imported entities;
   verify execution, history, uptime, events, alerts, retries, and documented maintenance behavior.
7. Deliver notifications/webhooks; verify templates/redaction, retry/dead-letter, DNS-rebinding SSRF,
   secret rotation, and duplicate suppression.
8. Restart API/workers between phases and reconcile IDs, counts, audit, and pending work.

## Primary tests

Extend backend auth/discovery/integration/monitor suites, `apps/agent/e2e/test_agent_release_gate.py`,
and production-browser E2E. Use direct DB reads only for invariants unavailable through supported APIs,
and label them as diagnostic assertions.

## Done

The continuous journey passes against release artifacts with no duplicate/lost durable effects,
cross-tenant leak, mocked transport substitution, or undocumented manual repair.
