import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../api/intel', () => ({ getBlastRadius: vi.fn() }));

import { getBlastRadius } from '../api/intel';
import BlastRadiusPanel from '../components/details/BlastRadiusPanel.jsx';

// Full BlastRadiusOut contract (schemas/intelligence.py). Paths, edges,
// connectivity, completeness and limits are plan 06's additions; the panel
// must render them rather than the bare count the old fixture carried.
const edge = (over = {}) => ({
  identity: 'compute_units.hardware_id:7:hardware:3:compute_unit:7',
  provider_type: 'hardware',
  provider_id: 3,
  dependent_type: 'compute_unit',
  dependent_id: 7,
  edge_type: 'hosting',
  provenance: 'confirmed',
  source_kind: 'compute_units.hardware_id',
  source_id: 7,
  label: 'hosted by',
  ...over,
});

const HOSTING_EDGE = edge();
const RUNS_ON_EDGE = edge({
  identity: 'services.compute_id:11:compute_unit:7:service:11',
  provider_type: 'compute_unit',
  provider_id: 7,
  dependent_type: 'service',
  dependent_id: 11,
  label: 'runs on',
});

const IMPACT = {
  root_asset: { asset_type: 'hardware', asset_id: 3, name: 'pve-01', status: 'online' },
  impacted_hardware: [],
  impacted_compute_units: [
    { asset_type: 'compute_unit', asset_id: 7, name: 'vm-postgres', status: 'running' },
    { asset_type: 'compute_unit', asset_id: 8, name: 'vm-jellyfin', status: 'running' },
  ],
  impacted_services: [{ asset_type: 'service', asset_id: 11, name: 'nextcloud', status: 'up' }],
  impacted_storage: [],
  total_impact_count: 3,
  summary: 'If pve-01 goes offline, 3 downstream assets lose availability.',
  paths: [
    {
      asset: { asset_type: 'compute_unit', asset_id: 7, name: 'vm-postgres', status: 'running' },
      edges: [HOSTING_EDGE],
      provenance: 'confirmed',
    },
    {
      asset: { asset_type: 'compute_unit', asset_id: 8, name: 'vm-jellyfin', status: 'running' },
      edges: [
        edge({
          identity: 'compute_units.hardware_id:8:hardware:3:compute_unit:8',
          dependent_id: 8,
          source_id: 8,
        }),
      ],
      provenance: 'confirmed',
    },
    {
      asset: { asset_type: 'service', asset_id: 11, name: 'nextcloud', status: 'up' },
      edges: [HOSTING_EDGE, RUNS_ON_EDGE],
      provenance: 'confirmed',
    },
  ],
  edges: [HOSTING_EDGE, RUNS_ON_EDGE],
  connectivity: [
    edge({
      identity: 'hardware_networks:1:network:2:hardware:3',
      provider_type: 'network',
      provider_id: 2,
      dependent_type: 'hardware',
      dependent_id: 3,
      edge_type: 'connectivity',
      source_kind: 'hardware_networks',
      source_id: 1,
      label: 'network membership',
    }),
  ],
  evaluated_at: '2026-09-15T12:00:00Z',
  completeness: 'complete',
  truncation_reason: null,
  limits: { max_nodes: 500, max_depth: 12, max_edges: 5000 },
  inferred_available: false,
};

const NO_IMPACT = {
  root_asset: { asset_type: 'hardware', asset_id: 5, name: 'nuc-05', status: 'online' },
  impacted_hardware: [],
  impacted_compute_units: [],
  impacted_services: [],
  impacted_storage: [],
  total_impact_count: 0,
  summary: 'Nothing depends on nuc-05.',
  paths: [],
  edges: [],
  connectivity: [],
  evaluated_at: '2026-09-15T12:00:00Z',
  completeness: 'complete',
  truncation_reason: null,
  limits: { max_nodes: 500, max_depth: 12, max_edges: 5000 },
  inferred_available: false,
};

const TRUNCATED_EMPTY = {
  ...NO_IMPACT,
  completeness: 'truncated',
  truncation_reason: 'node_limit',
};

const INFERRED_AVAILABLE = {
  ...IMPACT,
  inferred_available: true,
};

const renderPanel = (props = {}) =>
  render(
    <MemoryRouter>
      <BlastRadiusPanel assetType="hardware" assetId={3} {...props} />
    </MemoryRouter>
  );

const openPanel = async () => {
  fireEvent.click(screen.getByRole('button', { name: /impact/i }));
};

beforeEach(() => vi.clearAllMocks());

describe('BlastRadiusPanel', () => {
  it('does not fetch until expanded — it walks the dependency graph', () => {
    renderPanel();
    expect(getBlastRadius).not.toHaveBeenCalled();
  });

  it('fetches once on expand, with the asset type, id and evidence scope', async () => {
    getBlastRadius.mockResolvedValue({ data: IMPACT });
    renderPanel();
    await openPanel();
    await waitFor(() =>
      expect(getBlastRadius).toHaveBeenCalledWith('hardware', 3, { include_inferred: false })
    );
    expect(getBlastRadius).toHaveBeenCalledTimes(1);
  });

  it('does not refetch when collapsed and expanded again', async () => {
    getBlastRadius.mockResolvedValue({ data: IMPACT });
    renderPanel();
    const toggle = screen.getByRole('button', { name: /impact/i });
    fireEvent.click(toggle);
    await waitFor(() => expect(screen.getAllByText('vm-postgres').length).toBeGreaterThan(0));
    fireEvent.click(toggle);
    fireEvent.click(toggle);
    expect(getBlastRadius).toHaveBeenCalledTimes(1);
  });

  it('groups impacted assets by type and links each one', async () => {
    getBlastRadius.mockResolvedValue({ data: IMPACT });
    renderPanel();
    await openPanel();
    await waitFor(() => expect(screen.getAllByText('vm-postgres').length).toBeGreaterThan(0));
    expect(screen.getAllByText('nextcloud').length).toBeGreaterThan(0);
    expect(screen.getByRole('link', { name: 'vm-postgres' }).getAttribute('href')).toBe(
      '/compute-units?id=7'
    );
  });

  it('renders zero impact as an answer, not an empty state', async () => {
    getBlastRadius.mockResolvedValue({ data: NO_IMPACT });
    renderPanel({ assetId: 5 });
    await openPanel();
    await waitFor(() => expect(screen.getByText(/^Nothing depends on this./)).toBeInTheDocument());
    expect(screen.queryByText(/no data/i)).not.toBeInTheDocument();
  });

  it('renders an error with retry rather than an empty impact list', async () => {
    getBlastRadius.mockRejectedValue(new Error('boom'));
    renderPanel();
    await openPanel();
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });

  it('states potential impact, not observed outage, above every result', async () => {
    getBlastRadius.mockResolvedValue({ data: IMPACT });
    renderPanel();
    await openPanel();
    await waitFor(() =>
      expect(screen.getByText(/potential dependency impact/i)).toBeInTheDocument()
    );
    expect(screen.getByText(/not an observed outage/i)).toBeInTheDocument();
  });

  it('shows the path behind a listed effect when asked why', async () => {
    getBlastRadius.mockResolvedValue({ data: IMPACT });
    renderPanel();
    await openPanel();
    await waitFor(() => expect(screen.getAllByRole('button', { name: /why/i }).length).toBe(3));
    // Open the two-hop service path: hardware → compute → service.
    fireEvent.click(screen.getAllByRole('button', { name: /why/i })[2]);
    expect(screen.getByText(/impact flows from pve-01 outward/i)).toBeInTheDocument();
    // The chained steps render in dependency direction, read backwards.
    expect(screen.getByText('—hosted by→')).toBeInTheDocument();
    expect(screen.getByText('—runs on→')).toBeInTheDocument();
  });

  it('renders a truncated traversal as partial, never as exhaustive', async () => {
    getBlastRadius.mockResolvedValue({
      data: { ...IMPACT, completeness: 'truncated', truncation_reason: 'node_limit' },
    });
    renderPanel();
    await openPanel();
    await waitFor(() => expect(screen.getByText(/stopped at its node limit/i)).toBeInTheDocument());
  });

  it('does not claim nothing depends on an asset when the traversal was truncated', async () => {
    getBlastRadius.mockResolvedValue({ data: TRUNCATED_EMPTY });
    renderPanel({ assetId: 5 });
    await openPanel();
    await waitFor(() =>
      expect(
        screen.getByText(/No dependents found within the traversed portion/i)
      ).toBeInTheDocument()
    );
    expect(screen.getByText(/inconclusive rather than as proof/i)).toBeInTheDocument();
    expect(screen.queryByText(/^Nothing depends on this./)).not.toBeInTheDocument();
  });

  it('offers the inferred-evidence toggle only when inferred edges exist', async () => {
    getBlastRadius.mockResolvedValue({ data: IMPACT });
    renderPanel();
    await openPanel();
    await waitFor(() => expect(screen.getAllByText('vm-postgres').length).toBeGreaterThan(0));
    expect(
      screen.queryByRole('checkbox', { name: /include inferred relationships/i })
    ).not.toBeInTheDocument();
  });

  it('refetches with the inferred scope when the toggle is switched', async () => {
    getBlastRadius.mockResolvedValue({ data: INFERRED_AVAILABLE });
    renderPanel();
    await openPanel();
    await waitFor(() =>
      expect(
        screen.getByRole('checkbox', { name: /include inferred relationships/i })
      ).toBeInTheDocument()
    );
    fireEvent.click(screen.getByRole('checkbox', { name: /include inferred relationships/i }));
    await waitFor(() =>
      expect(getBlastRadius).toHaveBeenLastCalledWith('hardware', 3, { include_inferred: true })
    );
    expect(screen.getByText(/scope of evidence/i)).toBeInTheDocument();
  });

  it('lists connectivity separately and never counts it as impact', async () => {
    getBlastRadius.mockResolvedValue({ data: IMPACT });
    renderPanel();
    await openPanel();
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /also connected \(1\)/i })).toBeInTheDocument()
    );
    fireEvent.click(screen.getByRole('button', { name: /also connected \(1\)/i }));
    expect(screen.getByText(/network membership/)).toBeInTheDocument();
    // The connectivity member is the root itself — it must not appear as an impacted asset.
    expect(screen.getByText('3 assets affected')).toBeInTheDocument();
  });

  it('drops an earlier asset’s answer when the selection changes mid-flight', async () => {
    let releaseFirst;
    const first = new Promise((resolve) => {
      releaseFirst = () => resolve({ data: IMPACT });
    });
    getBlastRadius.mockReturnValueOnce(first).mockResolvedValueOnce({
      data: NO_IMPACT,
    });
    const { rerender } = renderPanel();
    await openPanel();
    // Selection changes before the first answer arrives.
    rerender(
      <MemoryRouter>
        <BlastRadiusPanel assetType="hardware" assetId={5} />
      </MemoryRouter>
    );
    releaseFirst();
    await waitFor(() => expect(screen.getByText(/^Nothing depends on this./)).toBeInTheDocument());
    // The superseded answer for pve-01 must never render under nuc-05's heading.
    expect(screen.queryByText(/pve-01 goes offline/i)).not.toBeInTheDocument();
  });

  it('refetches when the selection changes while open', async () => {
    getBlastRadius.mockResolvedValue({ data: IMPACT });
    const { rerender } = renderPanel();
    await openPanel();
    await waitFor(() => expect(screen.getAllByText('vm-postgres').length).toBeGreaterThan(0));
    rerender(
      <MemoryRouter>
        <BlastRadiusPanel assetType="hardware" assetId={5} />
      </MemoryRouter>
    );
    await waitFor(() =>
      expect(getBlastRadius).toHaveBeenLastCalledWith('hardware', 5, {
        include_inferred: false,
      })
    );
  });

  it('skips the focused graph for large results and says the list is the answer', async () => {
    const many = Array.from({ length: 60 }, (_, i) => ({
      asset_type: 'compute_unit',
      asset_id: 100 + i,
      name: `vm-${i}`,
      status: 'running',
    }));
    getBlastRadius.mockResolvedValue({
      data: {
        ...IMPACT,
        impacted_compute_units: many,
        total_impact_count: many.length,
        paths: many.map((asset) => ({
          asset,
          edges: [
            edge({
              identity: `e:${asset.asset_id}`,
              dependent_id: asset.asset_id,
              source_id: asset.asset_id,
            }),
          ],
          provenance: 'confirmed',
        })),
        edges: many.map((asset) =>
          edge({
            identity: `e:${asset.asset_id}`,
            dependent_id: asset.asset_id,
            source_id: asset.asset_id,
          })
        ),
      },
    });
    renderPanel();
    await openPanel();
    await waitFor(() =>
      expect(screen.getByText(/too large to draw as a graph/i)).toBeInTheDocument()
    );
  });
});
