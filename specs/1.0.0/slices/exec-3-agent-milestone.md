# EXEC-3 — cb-agent Milestone

**Requirement:** EXEC-03
**Depends on:** EXEC-1 and relevant identity/tenant security contracts

## Implementation sequence

1. Stabilize the composed release gate before relying on it for later UX/field evidence.
2. Resolve ARM64 AVIF, PyInstaller extraction, and environment-filter defects with exact artifact tests.
3. Complete discovered-device monitor creation, state/error semantics, destructive confirmations/audit,
   fleet operations, resource bounds, and recovery runbooks.
4. Run Go race/vet, backend agent API/service/conformance tests, frontend agent tests, composed E2E,
   package install/restart, update/rollback, and uninstall on one compatible candidate set.
5. Execute two-site physical UAT across the RC-02 OS/architecture/network matrix using signed artifacts.
6. Attach issue #101 evidence and reconcile remaining agent skip/xfail/warning with RC-08.

## Candidate control and done

Record server and agent digests together. Protocol, enrollment, key, scope, update, packaging, or server
agent-service changes invalidate applicable evidence. Done requires AGT-01 through AGT-18, both signed
physical sites, #101 evidence, and proof of outbound-only operation without an inbound firewall rule.
