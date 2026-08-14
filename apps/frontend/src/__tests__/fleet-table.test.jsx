import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import FleetTable from '../components/agents/FleetTable';

/**
 * The chrome around the rows: sort state, the pinned-pending ordering and the
 * two empty states. Three things here are load-bearing enough that the design
 * names them:
 *
 *   - Pending rows pin to the top of this same list and stay there through any
 *     column sort. They replaced a floating banner, so "sort by CPU" must not
 *     be able to bury a machine that is waiting on a human — which is exactly
 *     what a naive `rows.sort()` would do.
 *   - "Filters match nothing" gets a real empty state with a way out, not a
 *     bare colSpan cell that leaves the operator to work out why the fleet
 *     vanished.
 *   - A failed presence poll dims the values and says how old they are. Frozen
 *     numbers that still look live are the failure mode of the whole redesign.
 */

vi.mock('../api/agents', async () => {
  const actual = await vi.importActual('../api/agents');
  return { normalizeCapability: actual.normalizeCapability };
});

const baseAgent = (id, name, overrides = {}) => ({
  id,
  name,
  hostname: `${name}-host`,
  status: 'active',
  os: 'linux',
  arch: 'amd64',
  agent_version: '0.1.0',
  online: true,
  capabilities: {},
  hardware: null,
  last_seen_at: '2026-08-14T10:00:00Z',
  latest: { collected_at: '2026-08-14T10:00:00Z', cpu_pct: 10, uptime_s: 3600 },
  ...overrides,
});

const PENDING = {
  id: 1,
  name: null,
  hostname: 'zzz-pending',
  status: 'pending',
  os: 'linux',
  arch: 'amd64',
  fingerprint: 'a'.repeat(32),
  online: null,
  capabilities: {},
  hardware: null,
  latest: null,
};

// Deliberately adversarial for a "pending sinks to the bottom" bug: its
// hostname sorts last alphabetically, it has no CPU value at all (nullish
// values sort last), and it is not online.
const BUSY = baseAgent(2, 'aaa-busy', {
  latest: { collected_at: '2026-08-14T10:00:00Z', cpu_pct: 91, uptime_s: 7200 },
});
const IDLE = baseAgent(3, 'mmm-idle', {
  latest: { collected_at: '2026-08-14T10:00:00Z', cpu_pct: 4, uptime_s: 60 },
});
const DARK = baseAgent(4, 'nnn-dark', { latest: null, online: false });

function renderTable(props = {}) {
  return render(
    <MemoryRouter>
      <FleetTable rows={[PENDING, BUSY, IDLE, DARK]} {...props} />
    </MemoryRouter>
  );
}

/** Body rows in render order, skipping the header row. */
const bodyRows = () => within(screen.getByRole('table')).getAllByRole('row').slice(1);

const nameOf = (row) => within(row).getAllByRole('cell')[0].textContent;

const sortBy = (label) => fireEvent.click(screen.getByRole('button', { name: label }));

describe('FleetTable pinned pending ordering', () => {
  it('puts pending first even though every sort key would sort it last', () => {
    renderTable();

    const rows = bodyRows();
    expect(rows[0]).toHaveAttribute('data-state', 'pending');
    expect(nameOf(rows[0])).toContain('zzz-pending');
    // The fleet underneath is in the default sort: name ascending.
    expect(nameOf(rows[1])).toContain('aaa-busy');
  });

  it('keeps pending pinned through a column sort, in both directions', () => {
    renderTable();

    sortBy('CPU');
    let rows = bodyRows();
    expect(rows[0]).toHaveAttribute('data-state', 'pending');
    // Ascending: the idlest host first, and the agent with no reading at all
    // sinks to the bottom — a missing value is not a small value.
    expect(nameOf(rows[1])).toContain('mmm-idle');
    expect(nameOf(rows[2])).toContain('aaa-busy');
    expect(nameOf(rows[3])).toContain('nnn-dark');

    sortBy('CPU');
    rows = bodyRows();
    // Descending flips the fleet but not the pin, and still leaves the unknown
    // value at the bottom rather than promoting it to "the busiest host".
    expect(rows[0]).toHaveAttribute('data-state', 'pending');
    expect(nameOf(rows[1])).toContain('aaa-busy');
    expect(nameOf(rows[2])).toContain('mmm-idle');
    expect(nameOf(rows[3])).toContain('nnn-dark');
  });

  it('sorts several pending rows among themselves without letting fleet rows between them', () => {
    const otherPending = { ...PENDING, id: 5, hostname: 'aaa-pending' };
    render(
      <MemoryRouter>
        <FleetTable rows={[PENDING, BUSY, otherPending, IDLE]} />
      </MemoryRouter>
    );

    sortBy('CPU');
    const rows = bodyRows();
    expect(nameOf(rows[0])).toContain('aaa-pending');
    expect(nameOf(rows[1])).toContain('zzz-pending');
    expect(rows[2]).not.toHaveAttribute('data-state', 'pending');
  });

  it('announces the active sort column to assistive tech', () => {
    renderTable();

    const header = () => screen.getByRole('button', { name: 'CPU' }).closest('th');
    expect(header()).toHaveAttribute('aria-sort', 'none');
    sortBy('CPU');
    expect(header()).toHaveAttribute('aria-sort', 'ascending');
    sortBy('CPU');
    expect(header()).toHaveAttribute('aria-sort', 'descending');
  });
});

describe('FleetTable empty states', () => {
  it('explains an empty result and offers the way out of it', () => {
    const onClearFilters = vi.fn();
    render(
      <MemoryRouter>
        <FleetTable rows={[]} isFiltered onClearFilters={onClearFilters} />
      </MemoryRouter>
    );

    expect(screen.getByText('No agents match the current filters.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }));
    expect(onClearFilters).toHaveBeenCalled();
  });

  it('does not count a pinned pending row as "something matched"', () => {
    // Pending rows are pinned above the filters rather than subject to them, so
    // a filter that matches no fleet row still has nothing to show — and saying
    // so is what stops the operator hunting for the agents they filtered away.
    render(
      <MemoryRouter>
        <FleetTable rows={[PENDING]} isFiltered onClearFilters={vi.fn()} />
      </MemoryRouter>
    );

    expect(screen.getByText('No agents match the current filters.')).toBeInTheDocument();
    expect(screen.getByText(/Waiting for approval/i)).toBeInTheDocument();
  });

  it('renders no chrome at all for an empty, unfiltered fleet', () => {
    // Design §4 state 1: the Add-agent panel *is* the page. An empty
    // 11-column header is a worse answer than a guided flow.
    render(
      <MemoryRouter>
        <FleetTable rows={[]} />
      </MemoryRouter>
    );

    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });
});

describe('FleetTable stale treatment', () => {
  it('keeps the last good values and says how old they are', () => {
    const twoMinutesAgo = Date.now() - 2 * 60 * 1000;
    renderTable({ isStale: true, lastUpdatedAt: twoMinutesAgo });

    // Kept, not blanked: an old reading an operator can date is worth more than
    // an empty column, as long as the page admits it is old.
    expect(screen.getByText('91%')).toBeInTheDocument();
    expect(screen.getByRole('table')).toHaveAttribute('data-stale', 'true');
    expect(screen.getByText(/Last updated 2 minutes ago/i)).toBeInTheDocument();
  });

  it('says nothing while the poll is healthy', () => {
    renderTable({ isStale: false, lastUpdatedAt: Date.now() });

    expect(screen.getByRole('table')).not.toHaveAttribute('data-stale');
    expect(screen.queryByText(/Last updated/i)).not.toBeInTheDocument();
  });
});

describe('FleetTable wiring', () => {
  it('hands the whole row to each action so the page never re-looks it up', () => {
    const onReview = vi.fn();
    const onRevoke = vi.fn();
    renderTable({ onReview, onRevoke });

    fireEvent.click(within(bodyRows()[0]).getByRole('button', { name: 'Review' }));
    expect(onReview).toHaveBeenCalledWith(expect.objectContaining({ id: PENDING.id }));

    fireEvent.click(within(bodyRows()[1]).getByRole('button', { name: 'Revoke' }));
    expect(onRevoke).toHaveBeenCalledWith(expect.objectContaining({ id: BUSY.id }));
  });

  it('labels itself so the fleet is findable among the other tables on the page', () => {
    renderTable();

    expect(screen.getByRole('table', { name: 'Fleet' })).toBeInTheDocument();
  });
});
