import { expect, test } from '@playwright/test';
import { expectNoErrorBoundary, stubApi, waitForRouteSettled } from './fixtures/api';

/**
 * AGT-13, in a real browser: "A discovered/imported device can create a monitor
 * with the discovering agent visibly preselected as vantage."
 *
 * The unit suites cover the two halves separately — the link Agent Detail
 * builds (monitor-from-agent.test.jsx) and the form MonitorsPage opens from it
 * (monitors-page-create-from-agent-link.test.jsx). Neither proves they meet:
 * that a click on the device row lands on a create form whose vantage select is
 * actually showing the discovering agent. That join is what breaks silently
 * (a renamed query parameter, a route that drops the search string), and it is
 * what this spec exists to hold.
 *
 * The API is stubbed at the network layer like every other spec here — see
 * playwright.config.ts on why this suite is backend-free. The full-stack
 * version of this journey, against real hardware discovered by a real agent,
 * belongs to the composed agent gate (AGT-01/AGT-02), not here.
 */

const AGENT_ID = 7;

const AGENT = {
  id: AGENT_ID,
  name: 'branch-office',
  hostname: 'branch-office',
  status: 'active',
  os: 'linux',
  arch: 'amd64',
  agent_version: '0.9.0',
  fingerprint: 'a'.repeat(32),
  device_pk: 'b'.repeat(64),
  machine_id_hash: null,
  reported_ip: '10.77.0.2',
  tenant_id: null,
  notes: null,
  hardware_id: null,
  enrolled_at: '2026-08-01T10:00:00Z',
  approved_at: '2026-08-01T10:05:00Z',
  connected_since: '2026-08-26T09:00:00Z',
  last_seen_at: '2026-08-26T09:30:00Z',
  capabilities: {
    host_telemetry: { enabled: true, config: { interval_s: 30 } },
    remote_probe: { enabled: true, config: {} },
    local_discovery: { enabled: true, config: {} },
  },
  proposed_hardware_id: null,
  proposed_hardware_name: null,
  duplicate_machine_id: false,
};

// One accepted finding: merged into Hardware 55, which is what makes it a
// legitimate monitor target — a monitor points at an inventory record, never at
// a pending discovery result.
const ACCEPTED_DEVICE = {
  id: 1,
  ip_address: '10.77.0.11',
  hostname: 'branch-nas',
  merge_status: 'merged',
  matched_entity_type: 'hardware',
  matched_entity_id: 55,
  discovery_agent_id: AGENT_ID,
};

const ELIGIBLE_AGENT = {
  agent_id: AGENT_ID,
  name: 'branch-office',
  online: true,
  granted: true,
  readiness: 'ready',
  readiness_collector: 'probe.icmp',
  max_concurrent: 20,
  active_runs: 0,
  assigned_monitors: 0,
  scope_version: 'gen-3',
  scope_networks: ['10.77.0.0/24'],
  excluded_networks: [],
  in_scope: true,
  eligible: true,
  reason: null,
};

const OVERRIDES = {
  [`agents/${AGENT_ID}`]: AGENT,
  [`agents/${AGENT_ID}/events`]: [],
  [`agents/${AGENT_ID}/probes`]: {
    agent_id: AGENT_ID,
    max_concurrent: 20,
    active_runs: 0,
    assignments: [],
  },
  [`agents/${AGENT_ID}/telemetry`]: { latest: null, readiness: [], capability: {}, spool: {} },
  [`agents/${AGENT_ID}/telemetry/history`]: { points: [] },
  [`agents/${AGENT_ID}/discovery`]: {
    agent_id: AGENT_ID,
    online: true,
    granted: true,
    paused: false,
    globally_paused: false,
    eligible: true,
    reason: null,
    detail: null,
    scope_version: 'gen-3',
    scope: [{ cidr: '10.77.0.0/24', provenance: 'automatic', effective: true, reason: null }],
    limits: { max_addresses_per_job: 1024 },
    readiness: [],
    active_jobs: [],
    recent_jobs: [],
    profiles: [],
  },
  'agents/presence': [
    {
      agent_id: AGENT_ID,
      online: true,
      connected_since: '2026-08-26T09:00:00Z',
      last_seen_at: '2026-08-26T09:30:00Z',
      capabilities: AGENT.capabilities,
      hardware: null,
      latest: null,
    },
  ],
  'agents/capability-defaults': {
    host_telemetry: { enabled: true, config: { interval_s: 30 } },
    remote_probe: { enabled: true, config: {} },
    local_discovery: { enabled: true, config: {} },
  },
  'agents/probe-eligible': [ELIGIBLE_AGENT],
  'discovery/results': [ACCEPTED_DEVICE],
};

test('a device this agent discovered opens a monitor form with that agent as the vantage', async ({
  page,
}) => {
  await stubApi(page, OVERRIDES);

  // The discovered-devices table lives on the detail page's Discovery tab
  // (Task 14). Deep-linking with ?tab= rather than clicking is deliberate:
  // it is the same contract the rest of this test asserts about links.
  await page.goto(`/agents/${AGENT_ID}?tab=discovery`);
  await waitForRouteSettled(page);
  await expectNoErrorBoundary(page, 'agent detail');

  const deviceRow = page
    .getByRole('table', { name: 'Devices found by this agent' })
    .getByRole('row', {
      name: /branch-nas/,
    });
  await expect(deviceRow).toBeVisible();

  await deviceRow.getByRole('link', { name: 'Create monitor' }).click();

  // The link is the contract between the two pages; asserting on it here is
  // what catches a renamed parameter before the form silently loses the seed.
  await expect(page).toHaveURL(new RegExp(`probe_agent_id=${AGENT_ID}`));
  await expect(page).toHaveURL(/target_type=hardware/);
  await expect(page).toHaveURL(/target_id=55/);

  await waitForRouteSettled(page);
  await expectNoErrorBoundary(page, 'monitors');

  // The point of the whole flow: the form is open, on the discovered device,
  // with the discovering agent already chosen — and saying so out loud.
  await expect(page.getByLabel('Host')).toHaveValue('10.77.0.11');
  const runFrom = page.getByLabel('Run from');
  await expect(runFrom).toHaveValue(String(AGENT_ID));
  await expect(runFrom.locator('option:checked')).toHaveText(/branch-office/);
  await expect(page.getByText(/Vantage preselected: branch-office/)).toBeVisible();

  // …and still changeable, which is what "preselected" has to mean.
  await runFrom.selectOption('');
  await expect(runFrom).toHaveValue('');
});
