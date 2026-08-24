import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

vi.mock('../api/intel', () => ({
  listCapacityForecasts: vi.fn(),
  listResourceEfficiency: vi.fn(),
  getBlastRadius: vi.fn(),
}));

import { listCapacityForecasts, listResourceEfficiency } from '../api/intel';
import IntelPage from '../pages/IntelPage.jsx';

const FORECAST = {
  id: 1,
  hardware_id: 12,
  hardware_name: 'nas-01',
  metric: 'disk',
  slope_per_day: 0.9,
  current_value: 87,
  projected_full_at: '2026-09-07T00:00:00Z',
  warning_threshold_days: 30,
  evaluated_at: '2026-08-24T02:30:00Z',
};

const EFFICIENCY = {
  id: 1,
  asset_type: 'compute_unit',
  asset_id: 7,
  asset_name: 'vm-jellyfin',
  classification: 'over_provisioned',
  cpu_avg_pct: 3,
  cpu_peak_pct: 11,
  mem_avg_pct: 18,
  recommendation: 'Reduce from 8 vCPU to 2',
  evaluated_at: '2026-08-24T02:30:00Z',
};

beforeEach(() => {
  vi.clearAllMocks();
  listCapacityForecasts.mockResolvedValue({ data: [] });
  listResourceEfficiency.mockResolvedValue({ data: [] });
});

describe('IntelPage', () => {
  it('renders asset names, never bare ids', async () => {
    listCapacityForecasts.mockResolvedValue({ data: [FORECAST] });
    listResourceEfficiency.mockResolvedValue({ data: [EFFICIENCY] });

    render(<IntelPage />);

    await waitFor(() => expect(screen.getByText('nas-01')).toBeInTheDocument());
    expect(screen.getByText('vm-jellyfin')).toBeInTheDocument();
  });

  it('falls back to a labelled id when the asset no longer exists', async () => {
    listResourceEfficiency.mockResolvedValue({
      data: [{ ...EFFICIENCY, asset_name: null, asset_id: 999 }],
    });

    render(<IntelPage />);

    await waitFor(() => expect(screen.getByText(/compute_unit #999/)).toBeInTheDocument());
  });

  it('marks a forecast projected to saturate inside its warning threshold', async () => {
    listCapacityForecasts.mockResolvedValue({ data: [FORECAST] });

    render(<IntelPage />);

    await waitFor(() =>
      expect(screen.getByTestId('forecast-row-1')).toHaveAttribute('data-warning', 'true')
    );
  });

  it('does not mark a forecast with no projected saturation', async () => {
    listCapacityForecasts.mockResolvedValue({
      data: [{ ...FORECAST, id: 2, projected_full_at: null }],
    });

    render(<IntelPage />);

    await waitFor(() =>
      expect(screen.getByTestId('forecast-row-2')).toHaveAttribute('data-warning', 'false')
    );
  });

  it('names the job and both reasons a list can be empty', async () => {
    render(<IntelPage />);

    await waitFor(() => expect(screen.getAllByText(/analytics job/i).length).toBeGreaterThan(0));
    expect(screen.getAllByText(/02:30/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/has not run yet|enough history/i).length).toBeGreaterThan(0);
  });

  it('renders an error with retry rather than an empty table', async () => {
    listCapacityForecasts.mockRejectedValue(new Error('boom'));

    render(<IntelPage />);

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });
});
