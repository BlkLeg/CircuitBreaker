import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../api/intel', () => ({ getBlastRadius: vi.fn() }));

import { getBlastRadius } from '../api/intel';
import BlastRadiusPanel from '../components/details/BlastRadiusPanel.jsx';

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
};

const NO_IMPACT = {
  root_asset: { asset_type: 'hardware', asset_id: 5, name: 'nuc-05', status: 'online' },
  impacted_hardware: [],
  impacted_compute_units: [],
  impacted_services: [],
  impacted_storage: [],
  total_impact_count: 0,
  summary: 'Nothing depends on nuc-05.',
};

const renderPanel = (props = {}) =>
  render(
    <MemoryRouter>
      <BlastRadiusPanel assetType="hardware" assetId={3} {...props} />
    </MemoryRouter>
  );

beforeEach(() => vi.clearAllMocks());

describe('BlastRadiusPanel', () => {
  it('does not fetch until expanded — it walks the dependency graph', () => {
    renderPanel();
    expect(getBlastRadius).not.toHaveBeenCalled();
  });

  it('fetches once on expand, with the asset type and id', async () => {
    getBlastRadius.mockResolvedValue({ data: IMPACT });
    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: /impact/i }));
    await waitFor(() => expect(getBlastRadius).toHaveBeenCalledWith('hardware', 3));
  });

  it('does not refetch when collapsed and expanded again', async () => {
    getBlastRadius.mockResolvedValue({ data: IMPACT });
    renderPanel();
    const toggle = screen.getByRole('button', { name: /impact/i });
    fireEvent.click(toggle);
    await waitFor(() => expect(screen.getByText('vm-postgres')).toBeInTheDocument());
    fireEvent.click(toggle);
    fireEvent.click(toggle);
    expect(getBlastRadius).toHaveBeenCalledTimes(1);
  });

  it('groups impacted assets by type and links each one', async () => {
    getBlastRadius.mockResolvedValue({ data: IMPACT });
    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: /impact/i }));
    await waitFor(() => expect(screen.getByText('vm-postgres')).toBeInTheDocument());
    expect(screen.getByText('nextcloud')).toBeInTheDocument();
  });

  it('renders zero impact as an answer, not an empty state', async () => {
    getBlastRadius.mockResolvedValue({ data: NO_IMPACT });
    renderPanel({ assetId: 5 });
    fireEvent.click(screen.getByRole('button', { name: /impact/i }));
    await waitFor(() => expect(screen.getByText(/^Nothing depends on this./)).toBeInTheDocument());
    expect(screen.queryByText(/no data/i)).not.toBeInTheDocument();
  });

  it('renders an error with retry rather than an empty impact list', async () => {
    getBlastRadius.mockRejectedValue(new Error('boom'));
    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: /impact/i }));
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });
});
