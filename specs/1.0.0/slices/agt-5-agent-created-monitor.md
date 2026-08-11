# AGT-5 — Agent-Created Monitor Workflow

**Requirement:** AGT-13
**Primary files:** `apps/frontend/src/pages/AgentDetailPage.jsx`, `MonitorsPage.jsx`,
`components/monitors/MonitorForm.jsx`, `RunFromSelect.jsx`, agent/discovery review UI

## Build sequence

1. Confirm placement against `specs/2026-07-26-cb-agent-design.md` §7 and write a failing RTL test.
2. Define a typed/declarative deep-link state containing target type/ID and discovering agent ID;
   reject stale or unauthorized identifiers after server validation.
3. Add the action to the approved discovered/imported device surface. Navigate to monitor creation
   with the hardware target and agent vantage visibly preselected.
4. Reuse `MonitorForm` and `RunFromSelect`; avoid a second monitor-creation implementation. Permit an
   authorized user to change vantage and announce defaults accessibly.
5. Add loading/deleted device, revoked/offline agent, wrong tenant, insufficient scope, cancel, save
   failure, and successful execution behavior.
6. Extend the composed agent gate so the saved monitor actually runs against the discovered target.

## Verification

```bash
cd apps/frontend
npm test -- --run src/__tests__/monitor-from-agent.test.jsx \
  src/__tests__/monitors-page-create-from-agent-link.test.jsx
npm run lint
```

Then run browser E2E with the real API and AGT-1. Done means persisted `probe_agent_id` and target are
correct, execution succeeds from that agent, and unauthorized/stale links fail safely.
