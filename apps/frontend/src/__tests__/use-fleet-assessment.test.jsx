import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';

const fleet = vi.fn();
vi.mock('../api/client', () => ({ cveApi: { fleet: (...a) => fleet(...a) } }));

import { useFleetAssessment } from '../hooks/useFleetAssessment';

const PAYLOAD = {
  feed: { state: 'ready', reason_code: 'ready', generation: 'g1', age_seconds: 60 },
  assessed_at: '2026-09-17T10:00:00Z',
  summary: {
    total_entities: 2,
    by_state: { completed: 1, unassessed: 1 },
    entities_with_findings: 1,
    findings_total: 3,
    by_severity: { high: 1 },
  },
  rows: [
    {
      entity_type: 'hardware',
      entity_id: 1,
      name: 'nas-01',
      state: 'completed',
      reason_code: 'completed',
      identity: null,
      finding_count: 3,
      max_severity: 'high',
      max_cvss: 8.1,
      completeness: 'complete',
    },
    {
      entity_type: 'service',
      entity_id: 2,
      name: 'mystery',
      state: 'unassessed',
      reason_code: 'identity_missing',
      identity: null,
      finding_count: 0,
      max_severity: null,
      max_cvss: null,
      completeness: 'none',
    },
  ],
  limits: {
    identity_limit: 250,
    identities_total: 2,
    identities_assessed: 2,
    identity_limit_reached: false,
    candidate_limited_products: [],
  },
};

function Probe() {
  const { rows, loading, error, data, setFilters } = useFleetAssessment();
  if (loading) return <p>loading</p>;
  if (error) return <p role="alert">{error}</p>;
  return (
    <div>
      <p data-testid="names">{rows.map((r) => r.name).join(',')}</p>
      <p data-testid="total">{data.summary.total_entities}</p>
      <button type="button" onClick={() => setFilters({ stateFilter: 'needs_identity' })}>
        needs identity
      </button>
    </div>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  fleet.mockResolvedValue({ data: PAYLOAD });
});

describe('useFleetAssessment', () => {
  it('sorts rows and exposes the server summary untouched', async () => {
    render(<Probe />);

    await waitFor(() => expect(screen.getByTestId('names')).toHaveTextContent('nas-01,mystery'));
    expect(screen.getByTestId('total')).toHaveTextContent('2');
  });

  it('applies a filter without refetching', async () => {
    render(<Probe />);
    await waitFor(() => expect(screen.getByTestId('names')).toBeInTheDocument());

    await act(async () => {
      screen.getByRole('button', { name: /needs identity/i }).click();
    });

    expect(screen.getByTestId('names')).toHaveTextContent('mystery');
    expect(fleet).toHaveBeenCalledTimes(1);
  });

  it('surfaces a failure as an error rather than an empty table', async () => {
    fleet.mockRejectedValue({ userMessage: 'The assessment could not be read.' });

    render(<Probe />);

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByRole('alert')).toHaveTextContent('The assessment could not be read.');
  });
});
