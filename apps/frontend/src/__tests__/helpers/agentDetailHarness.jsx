// Shared render/data helpers for the AgentDetailPage split suites
// (agent-detail-*.test.jsx). Extracted verbatim from the single
// agent-detail-page.test.jsx this repo used to carry (Task 4 of the
// 2026-09-07 tech-debt cleanup) so every split file renders the page and
// reads its DOM the same way.
//
// This module intentionally does NOT export `apiDefaults` or call
// vi.mock(): a vi.mock('../api/agents', factory) call is hoisted above
// this file's own import of it, so a factory that reads `apiDefaults.*`
// needs `apiDefaults` declared locally via vi.hoisted() in the SAME file —
// importing it from here throws "Cannot access '__vi_import_N__' before
// initialization" (confirmed by actually running the split suites; see the
// Task 4 report). `apiDefaults` and the vi.mock('../api/agents', ...) call
// that reads it are therefore duplicated verbatim at the top of every
// split file instead. What lives here is REGISTRY_HOST_CONFIG (plain data,
// never read from inside a same-file vi.mock factory) and render/query
// helpers, neither of which carries that hoisting hazard.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { expect } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import AgentDetailPage from '../../pages/AgentDetailPage';

// The registry config the page must fall back to when a grant carries no
// config of its own — the same object each split file's own apiDefaults
// (see the file-local `getCapabilityDefaults`) declares.
export const REGISTRY_HOST_CONFIG = {
  interval_s: 45,
  include_filesystems: true,
  include_disks: true,
  include_network: true,
  include_temperatures: true,
  include_virtual: false,
  include_docker: false,
  include_gpu: true,
};

export function detailTree() {
  return (
    <MemoryRouter initialEntries={['/agents/3']}>
      <Routes>
        <Route path="/agents/:id" element={<AgentDetailPage />} />
      </Routes>
    </MemoryRouter>
  );
}

export function renderDetail() {
  return render(detailTree());
}

/**
 * Task 14: a section is only in the DOM while its tab is selected, so every
 * assertion about probes, discovery, telemetry or events has to ask for that
 * section first. `fireEvent` rather than `userEvent` on purpose — two tests
 * below drive the poll with fake timers, and userEvent's own timer advance
 * does not compose with them.
 */
export async function openTab(name) {
  fireEvent.click(await screen.findByRole('tab', { name }));
  return screen.findByRole('tabpanel');
}

/**
 * What the page says about the agent's state. The old <section aria-label="Agent
 * state"> held a chip row and a <dl> together; Task 14 splits the same wording
 * across the primary state's banner, the secondary states' header chips, and
 * the unverified-clock note, so the assertions that read one element read all
 * three.
 */
/**
 * How the header renders presence now: `composeAgentPage` dims the live strip
 * for an offline agent and leaves it lit for a connected one.
 */
export const stripDimmed = () =>
  document.querySelector('.agent-strip')?.getAttribute('data-dimmed');

export function stateText() {
  return [
    document.querySelector('.cb-detail-head__chips'),
    document.querySelector('.cb-banner'),
    document.querySelector('.agent-detail-page__last-seen'),
  ]
    .map((element) => element?.textContent ?? '')
    .join(' ');
}

// ── Task 19: the telemetry section, end to end ────────────────────────────
//
// Shape mirrors GET /api/v1/agents/{id}/telemetry (api/agents.py:288-303)
// plus Task 16's `spool` key. `latest` is merged shallowly so a test can
// override one field without restating the whole sample; passing
// `latest: null` clears it outright.
export function telemetryFixture({ latest, ...rest } = {}) {
  const base = {
    latest: {
      sample_id: '11111111-1111-4111-8111-111111111111',
      collected_at: new Date().toISOString(),
      status: 'ok',
      projected: true,
      summary: {
        cpu_pct: 12.5,
        mem_pct: 63.4,
        root_disk_pct: 41.2,
        net_rx_bps: 1234567.8,
        net_tx_bps: null,
        max_temp_c: 48.5,
        load_1: 1.234,
        uptime_s: 90061,
      },
      payload: {},
    },
    readiness: [],
    capability: { enabled: true, config: { interval_s: 30 } },
    hardware_id: 5,
    // Reported, drained, and reported *just now*: a depth with no report
    // time reads as "we cannot say what the backlog is", which is a
    // different agent from the healthy default these cases assume.
    spool: { depth: 0, bytes: 0, reported_at: new Date().toISOString() },
  };
  return {
    ...base,
    ...rest,
    latest: latest === null ? null : { ...base.latest, ...latest },
  };
}

/**
 * The Telemetry tab's own section. Task 14 put a live strip in the sticky
 * header that repeats CPU/MEM/DISK/NET/TEMP and their formatted values, so
 * an unscoped getByText('CPU') now matches two elements. Every assertion
 * about the cards is scoped here; the strip has its own suite
 * (agent-live-strip.test.jsx).
 */
export const telemetrySection = () => screen.getByRole('region', { name: 'Host telemetry' });

/** Waits for the summary cards to render, then returns the section. */
export const findCards = () =>
  waitFor(() => {
    within(telemetrySection()).getByText('CPU');
    return telemetrySection();
  });

// Task 16: a summary card is a StatTile — <div class="cb-tile"> with its
// label and value in their own elements — rather than the bare
// <article><span><strong> the page used to emit.
export function cardValue(label) {
  const tile = within(telemetrySection()).getByText(label).closest('.cb-tile');
  return tile.querySelector('.cb-tile__value').textContent;
}

/**
 * The readiness and truncation callouts on the Telemetry tab.
 *
 * Task 16 renders these as Banners, which are role="status" and not
 * role="alert" — every one of these conditions is already true when the tab
 * opens, and an alert would interrupt a screen reader on each navigation.
 * Scoped to the tab body because the page header carries a Banner of its own
 * for the primary agent state.
 */
export const telemetryBanners = () => within(telemetrySection()).queryAllByRole('status');

export const findTelemetryBanners = async () => {
  await waitFor(() => expect(telemetryBanners().length).toBeGreaterThan(0));
  return telemetryBanners();
};
