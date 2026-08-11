# AGT-6 — Agent State Semantics and Actionable Errors

**Requirements:** AGT-14, AGT-15
**Primary files:** `apps/frontend/src/utils/agentPresenceFreshness.js`, `pages/AgentDetailPage.jsx`,
agent API/schemas/services, agent status/enrollment/install/link packages

## Build sequence

1. Define a server-clock-based state machine and precedence for disabled, revoked, offline, stale
   telemetry, clock skew, degraded capability, pending configuration, and pending update.
2. Put stable machine codes/timestamps in backend schemas; keep wording in the client. Define unknown
   and contradictory-state handling instead of guessing green.
3. Use one freshness calculation across list/detail/live updates and avoid client-clock-only truth.
4. Map install, enrollment, TLS, pairing, approval, scope, update, and connectivity failures to safe
   codes with operator action and correlation ID. Redact keys, tokens, frames, and filesystem secrets.
5. Add transition, reconnect race, stale REST versus newer stream, clock skew, localization,
   accessibility, and log/API/UI redaction tests.

## Verification

Run Go status/link/enrollment tests, backend agent API/service tests, frontend presence/detail tests,
and browser live-stream scenarios. Done means each state is distinguishable, accessible, stable across
refresh/reconnect, actionable, and never leaks secret or raw protocol material.
