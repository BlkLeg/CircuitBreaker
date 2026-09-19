import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import FleetAssessmentTable from '../components/intel/FleetAssessmentTable.jsx';
import FleetSummaryStrip from '../components/intel/FleetSummaryStrip.jsx';

const ROWS = [
  {
    entity_type: 'hardware',
    entity_id: 1,
    name: 'nas-01',
    state: 'completed',
    reason_code: 'completed',
    identity: {
      vendor: 'acme',
      product: 'widget',
      version: '1.9',
      provenance: 'inventory',
      revision: 0,
    },
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
];

const renderTable = (props = {}) =>
  render(
    <MemoryRouter>
      <FleetAssessmentTable
        rows={ROWS}
        expandedKey={null}
        onToggleExpand={() => {}}
        onCorrectIdentity={() => {}}
        canWrite
        renderExpansion={() => <p>expanded</p>}
        {...props}
      />
    </MemoryRouter>
  );

describe('FleetAssessmentTable', () => {
  it('links each entity to its detail page rather than printing a bare id', () => {
    renderTable();

    expect(screen.getByRole('link', { name: 'nas-01' })).toHaveAttribute(
      'href',
      '/hardware?entity=1'
    );
  });

  it('shows a zero-finding assessed row as assessed, not as clean', () => {
    renderTable({ rows: [{ ...ROWS[0], finding_count: 0, max_severity: null }] });

    expect(screen.queryByText(/no known vulnerabilities/i)).not.toBeInTheDocument();
    expect(screen.getByText(/no matches in this assessment/i)).toBeInTheDocument();
  });

  it('does not label a row that has findings as having none', () => {
    renderTable({ rows: [ROWS[0]] });

    expect(screen.queryByText(/no matches in this assessment/i)).not.toBeInTheDocument();
  });

  it('offers identity correction only to a user who can write', () => {
    renderTable({ canWrite: false });

    expect(screen.queryByRole('button', { name: /correct identity/i })).not.toBeInTheDocument();
  });

  it('renders the expansion for the expanded row only', () => {
    renderTable({ expandedKey: 'hardware:1' });

    expect(screen.getByText('expanded')).toBeInTheDocument();
    expect(screen.getAllByText('expanded')).toHaveLength(1);
  });

  it('asks to expand when a row is activated', () => {
    const onToggleExpand = vi.fn();
    renderTable({ onToggleExpand });

    fireEvent.click(screen.getAllByRole('button', { name: /findings|assessment/i })[0]);

    expect(onToggleExpand).toHaveBeenCalledWith('hardware:1');
  });
});

describe('FleetSummaryStrip', () => {
  const SUMMARY = {
    total_entities: 12,
    by_state: { completed: 8, unassessed: 3, stale: 1 },
    entities_with_findings: 4,
    findings_total: 17,
    by_severity: { critical: 1, high: 3 },
  };

  it('counts readiness separately from findings', () => {
    render(<FleetSummaryStrip summary={SUMMARY} feed={{ state: 'ready', age_seconds: 60 }} />);

    expect(screen.getByTestId('tile-unassessed')).toHaveTextContent('3');
    expect(screen.getByTestId('tile-with-findings')).toHaveTextContent('4');
  });

  it('renders the severity histogram the summary carries', () => {
    render(<FleetSummaryStrip summary={SUMMARY} feed={{ state: 'ready', age_seconds: 60 }} />);

    const histogram = screen.getByTestId('fleet-severity');
    expect(histogram).toHaveTextContent(/critical/i);
    expect(histogram).toHaveTextContent('1');
    expect(histogram).toHaveTextContent(/high/i);
    expect(histogram).toHaveTextContent('3');
  });

  it('omits the histogram entirely when nothing has a finding', () => {
    render(
      <FleetSummaryStrip
        summary={{ ...SUMMARY, by_severity: {}, entities_with_findings: 0, findings_total: 0 }}
        feed={{ state: 'ready', age_seconds: 60 }}
      />
    );

    expect(screen.queryByTestId('fleet-severity')).not.toBeInTheDocument();
  });

  it('never renders a single aggregate score', () => {
    render(<FleetSummaryStrip summary={SUMMARY} feed={{ state: 'ready', age_seconds: 60 }} />);

    expect(screen.queryByText(/score/i)).not.toBeInTheDocument();
  });
});
