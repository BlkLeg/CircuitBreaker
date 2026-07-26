import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    default: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
    computeUnitsApi: {
      list: vi.fn().mockResolvedValue({
        data: [
          { id: 7, name: 'web-vm', kind: 'vm', hardware_id: 1, ip_address: '10.0.0.7', tags: [] },
        ],
      }),
      create: vi.fn(),
      update: vi.fn(),
      delete: vi.fn(),
    },
    hardwareApi: { list: vi.fn().mockResolvedValue({ data: [{ id: 1, name: 'host-a' }] }) },
    environmentsApi: { list: vi.fn().mockResolvedValue({ data: [] }) },
    tagsApi: { list: vi.fn().mockResolvedValue({ data: [] }), update: vi.fn() },
  };
});

vi.mock('../api/monitor', () => ({
  getTargetSummary: vi.fn(),
  createTargetMonitor: vi.fn().mockResolvedValue({ data: {} }),
  pauseTargetMonitor: vi.fn().mockResolvedValue({ data: {} }),
  resumeTargetMonitor: vi.fn().mockResolvedValue({ data: {} }),
  runTargetCheck: vi.fn().mockResolvedValue({ data: {} }),
}));

vi.mock('../hooks/useMonitorStream', () => ({
  useMonitorStream: () => ({ statuses: new Map(), connected: true }),
}));

const mockToast = { success: vi.fn(), error: vi.fn(), warn: vi.fn(), info: vi.fn() };
vi.mock('../components/common/Toast', () => ({ useToast: () => mockToast }));

vi.mock('../context/SettingsContext', () => ({
  useSettings: () => ({ settings: { show_page_hints: false }, reloadSettings: vi.fn() }),
}));

// Render the real monitor column + action cell, stub the rest of the table.
vi.mock('../components/EntityTable', () => ({
  default: ({ columns, data, renderMonitorAction }) =>
    React.createElement(
      'table',
      null,
      React.createElement(
        'thead',
        null,
        React.createElement(
          'tr',
          null,
          columns.map((col) => React.createElement('th', { key: col.key }, col.label))
        )
      ),
      React.createElement(
        'tbody',
        null,
        data.map((row) =>
          React.createElement(
            'tr',
            { key: row.id },
            columns.map((col) =>
              React.createElement(
                'td',
                { key: col.key },
                typeof col.render === 'function' ? col.render(row[col.key], row) : null
              )
            ),
            React.createElement('td', { key: 'actions' }, renderMonitorAction?.(row))
          )
        )
      )
    ),
}));

vi.mock('../components/SearchBox', () => ({ default: () => null }));
vi.mock('../components/TagFilter', () => ({ default: () => null }));
vi.mock('../components/TagsCell', () => ({ default: () => null }));
vi.mock('../components/details/ComputeDetail', () => ({ default: () => null }));
vi.mock('../components/common/FormModal', () => ({ default: () => null }));
vi.mock('../components/common/IconPickerModal', () => ({
  default: () => null,
  IconImg: () => null,
}));

import { createTargetMonitor, getTargetSummary, pauseTargetMonitor } from '../api/monitor';
import ComputeUnitsPage from '../pages/ComputeUnitsPage.jsx';

describe('ComputeUnitsPage monitoring', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getTargetSummary.mockResolvedValue({ data: [] });
  });

  it('renders a Monitor column and enables monitoring for the row', async () => {
    render(<ComputeUnitsPage />);

    // The column header and the row's enable button both read "Monitor".
    await waitFor(() => expect(screen.getAllByText('Monitor').length).toBeGreaterThanOrEqual(2));
    expect(screen.getByRole('columnheader', { name: 'Monitor' })).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Monitor' }));
    await waitFor(() =>
      expect(createTargetMonitor).toHaveBeenCalledWith('compute_unit', 7, undefined)
    );
    await waitFor(() => expect(mockToast.success).toHaveBeenCalledWith('Monitoring enabled.'));
  });

  it('shows live status and pause for an already-monitored unit', async () => {
    getTargetSummary.mockResolvedValue({
      data: [
        {
          target_type: 'compute_unit',
          target_id: 7,
          monitor_id: 31,
          monitor_ids: [31],
          enabled: true,
          status: 'up',
          latency_ms: 3,
          uptime_pct_24h: 100,
          last_polled_at: null,
        },
      ],
    });
    render(<ComputeUnitsPage />);

    await waitFor(() => expect(screen.getByText('Up')).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Pause' }));
    await waitFor(() => expect(pauseTargetMonitor).toHaveBeenCalledWith('compute_unit', 7));
    await waitFor(() => expect(mockToast.success).toHaveBeenCalledWith('Monitoring paused.'));
  });

  it('explains the failure when the unit has no address to probe', async () => {
    createTargetMonitor.mockRejectedValue({ response: { status: 404 } });
    render(<ComputeUnitsPage />);

    await waitFor(() => expect(screen.getByRole('button', { name: 'Monitor' })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Monitor' }));
    await waitFor(() =>
      expect(mockToast.error).toHaveBeenCalledWith('No address to probe — add an IP address first.')
    );
  });
});
