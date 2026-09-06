import React from 'react';
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { summarizeFleet, readFleetFilters } from '../lib/fleetFilters';
import { FleetSummary } from '../pages/AgentsPage';

const FILTERS = readFleetFilters(new URLSearchParams());

function summaryFor(rows) {
  return summarizeFleet(rows, FILTERS, {});
}

describe('FleetSummary', () => {
  it('does not claim a fleet of zero when the only agent is pending', () => {
    // The row is visible directly beneath this sentence. Saying "0 of 0
    // agents" contradicts what the operator can see.
    const summary = summaryFor([{ id: 1, status: 'pending', online: false }]);
    render(<FleetSummary summary={summary} />);
    const text = screen.getByRole('status').textContent;
    expect(text).toBe('1 awaiting approval');
    expect(text).not.toContain('0 of 0');
  });

  it('reports the fleet count once there is an approved agent', () => {
    const summary = summaryFor([
      { id: 1, status: 'pending', online: false },
      {
        id: 2,
        status: 'active',
        online: true,
        capabilities: { host_telemetry: { enabled: true } },
      },
    ]);
    render(<FleetSummary summary={summary} />);
    const text = screen.getByRole('status').textContent;
    expect(text).toContain('1 of 1 agents');
    expect(text).toContain('1 awaiting approval');
  });

  it('still reports an empty deployment as empty', () => {
    render(<FleetSummary summary={summaryFor([])} />);
    expect(screen.getByRole('status').textContent).toBe('0 of 0 agents');
  });

  it('keeps announcing changes as a status region', () => {
    render(<FleetSummary summary={summaryFor([{ id: 1, status: 'pending', online: false }])} />);
    expect(screen.getByRole('status')).toBeTruthy();
  });
});
