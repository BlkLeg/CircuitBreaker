import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const { mockUser } = vi.hoisted(() => ({ mockUser: { value: { role: 'admin' } } }));
vi.mock('../context/AuthContext', () => ({ useAuth: () => ({ user: mockUser.value }) }));

const fleet = vi.fn();
const forEntity = vi.fn();
const updateIdentity = vi.fn();
const status = vi.fn();
// An expanded row mounts VulnerabilityPanel, which calls cveApi.status() as well
// as forEntity(). A mock missing status throws inside the expansion and the test
// fails somewhere far from the cause.
vi.mock('../api/client', () => ({
  cveApi: {
    fleet: (...a) => fleet(...a),
    forEntity: (...a) => forEntity(...a),
    updateIdentity: (...a) => updateIdentity(...a),
    status: (...a) => status(...a),
  },
}));

import FleetAssessmentTab from '../components/intel/FleetAssessmentTab.jsx';

const ROW = {
  entity_type: 'hardware',
  entity_id: 1,
  name: 'nas-01',
  state: 'completed',
  reason_code: 'completed',
  identity: {
    vendor: 'acme',
    product: 'widget',
    version: '1.9',
    version_scheme: 'dotted_numeric',
    provenance: 'inventory',
    revision: 0,
  },
  finding_count: 1,
  max_severity: 'high',
  max_cvss: 8.1,
  completeness: 'complete',
};

const payload = (over = {}) => ({
  feed: { state: 'ready', reason_code: 'ready', generation: 'g1', age_seconds: 60 },
  assessed_at: '2026-09-17T10:00:00Z',
  summary: {
    total_entities: 1,
    by_state: { completed: 1 },
    entities_with_findings: 1,
    findings_total: 1,
    by_severity: { high: 1 },
  },
  rows: [ROW],
  limits: {
    identity_limit: 250,
    identities_total: 1,
    identities_assessed: 1,
    identity_limit_reached: false,
    candidate_limited_products: [],
  },
  ...over,
});

const renderTab = () =>
  render(
    <MemoryRouter>
      <FleetAssessmentTab />
    </MemoryRouter>
  );

beforeEach(() => {
  vi.clearAllMocks();
  mockUser.value = { role: 'admin' };
  fleet.mockResolvedValue({ data: payload() });
  status.mockResolvedValue({ data: { enabled: true, total_entries: 1 } });
  forEntity.mockResolvedValue({
    data: {
      state: 'completed',
      reason_code: 'completed',
      identity: ROW.identity,
      findings: [],
      limitations: [],
      assessed_at: '2026-09-17T10:00:00Z',
      completeness: 'complete',
      total: 0,
    },
  });
});

describe('FleetAssessmentTab', () => {
  it('shows a skeleton while loading, not a bare string', () => {
    renderTab();

    expect(screen.getByTestId('fleet-loading')).toBeInTheDocument();
  });

  it('renders the fleet once loaded', async () => {
    renderTab();

    await waitFor(() => expect(screen.getByText('nas-01')).toBeInTheDocument());
  });

  it('warns once when the feed has never been ingested', async () => {
    fleet.mockResolvedValue({
      data: payload({
        feed: {
          state: 'unavailable',
          reason_code: 'feed_missing',
          generation: null,
          age_seconds: null,
        },
        rows: [
          {
            ...ROW,
            state: 'unavailable',
            reason_code: 'feed_missing',
            finding_count: 0,
            max_severity: null,
          },
        ],
        summary: {
          total_entities: 1,
          by_state: { unavailable: 1 },
          entities_with_findings: 0,
          findings_total: 0,
          by_severity: {},
        },
      }),
    });

    renderTab();

    await waitFor(() => expect(screen.getAllByRole('status')).toHaveLength(1));
    expect(screen.getByRole('status')).toHaveTextContent(/feed/i);
  });

  it('says so when the pass ran out of budget', async () => {
    fleet.mockResolvedValue({
      data: payload({
        limits: {
          identity_limit: 2,
          identities_total: 9,
          identities_assessed: 2,
          identity_limit_reached: true,
          candidate_limited_products: [],
        },
      }),
    });

    renderTab();

    await waitFor(() => expect(screen.getByTestId('fleet-limits')).toBeInTheDocument());
    expect(screen.getByTestId('fleet-limits')).toHaveTextContent(/9/);
  });

  it('fetches the full assessment when a row is expanded', async () => {
    forEntity.mockResolvedValue({
      data: {
        state: 'completed',
        reason_code: 'completed',
        findings: [],
        limitations: [],
        identity: ROW.identity,
        assessed_at: '2026-09-17T10:00:00Z',
      },
    });
    renderTab();
    await waitFor(() => expect(screen.getByText('nas-01')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /1 findings/i }));

    await waitFor(() => expect(forEntity).toHaveBeenCalledWith('hardware', 1));
  });

  it('refetches the fleet after a correction so the summary stays authoritative', async () => {
    updateIdentity.mockResolvedValue({ data: { ...ROW.identity, revision: 1 } });
    renderTab();
    await waitFor(() => expect(screen.getByText('nas-01')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /correct identity/i }));
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));

    await waitFor(() => expect(fleet).toHaveBeenCalledTimes(2));
  });

  it('offers a severity floor, and applies it', async () => {
    fleet.mockResolvedValue({
      data: payload({
        rows: [
          ROW,
          {
            ...ROW,
            entity_id: 2,
            name: 'low-only',
            finding_count: 1,
            max_severity: 'low',
            max_cvss: 2.1,
          },
        ],
      }),
    });
    renderTab();
    await waitFor(() => expect(screen.getByText('low-only')).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/minimum severity/i), { target: { value: 'high' } });

    expect(screen.getByText('nas-01')).toBeInTheDocument();
    expect(screen.queryByText('low-only')).not.toBeInTheDocument();
  });

  it('renders an error with retry rather than an empty table', async () => {
    fleet.mockRejectedValue({ userMessage: 'boom' });

    renderTab();

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });
});
