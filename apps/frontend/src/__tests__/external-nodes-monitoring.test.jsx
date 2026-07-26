import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    default: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
    externalNodesApi: {
      list: vi.fn().mockResolvedValue({
        data: [
          {
            id: 12,
            name: 'hetzner-vps',
            provider: 'Hetzner',
            kind: 'vps',
            ip_address: '192.0.2.40',
            tags: [],
          },
        ],
      }),
      create: vi.fn(),
      update: vi.fn(),
      delete: vi.fn(),
    },
    networksApi: { list: vi.fn().mockResolvedValue({ data: [] }) },
    tagsApi: { list: vi.fn().mockResolvedValue({ data: [] }), update: vi.fn() },
  };
});

vi.mock('../api/monitor', () => ({
  getTargetSummary: vi.fn(),
  createTargetMonitor: vi.fn().mockResolvedValue({ data: {} }),
  pauseTargetMonitor: vi.fn().mockResolvedValue({ data: {} }),
  resumeTargetMonitor: vi.fn().mockResolvedValue({ data: {} }),
  runTargetCheck: vi.fn().mockResolvedValue({ data: {} }),
  getMonitorEvents: vi.fn().mockResolvedValue({ data: [] }),
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
vi.mock('../components/common/FormModal', () => ({ default: () => null }));
vi.mock('../components/common/Drawer', () => ({ default: () => null }));
vi.mock('../components/common/IconPickerModal', () => ({
  default: () => null,
  IconImg: () => null,
}));

import { createTargetMonitor, getTargetSummary, runTargetCheck } from '../api/monitor';
import ExternalNodesPage from '../pages/ExternalNodesPage.jsx';

describe('ExternalNodesPage monitoring', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getTargetSummary.mockResolvedValue({ data: [] });
  });

  it('enables monitoring for an external node row', async () => {
    render(<ExternalNodesPage />);

    await waitFor(() => expect(screen.getByRole('columnheader', { name: 'Monitor' })).toBeTruthy());

    fireEvent.click(screen.getByRole('button', { name: 'Monitor' }));
    await waitFor(() =>
      expect(createTargetMonitor).toHaveBeenCalledWith('external_node', 12, undefined)
    );
    await waitFor(() => expect(mockToast.success).toHaveBeenCalledWith('Monitoring enabled.'));
  });

  it('shows status and runs an on-demand check for a monitored node', async () => {
    getTargetSummary.mockResolvedValue({
      data: [
        {
          target_type: 'external_node',
          target_id: 12,
          monitor_id: 44,
          monitor_ids: [44],
          enabled: true,
          status: 'down',
          latency_ms: null,
          uptime_pct_24h: 42.5,
          last_polled_at: null,
        },
      ],
    });
    render(<ExternalNodesPage />);

    await waitFor(() => expect(screen.getByText('Down')).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Check' }));
    await waitFor(() => expect(runTargetCheck).toHaveBeenCalledWith('external_node', 12));
    await waitFor(() => expect(mockToast.success).toHaveBeenCalledWith('Probe triggered.'));
  });

  it('explains the failure when the node has no address to probe', async () => {
    createTargetMonitor.mockRejectedValue({ response: { status: 404 } });
    render(<ExternalNodesPage />);

    await waitFor(() => expect(screen.getByRole('button', { name: 'Monitor' })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Monitor' }));
    await waitFor(() =>
      expect(mockToast.error).toHaveBeenCalledWith(
        'No address to probe — add an IP address or hostname first.'
      )
    );
  });
});
