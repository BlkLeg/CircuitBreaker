/**
 * The review queue's handling of devices discovery already knows.
 *
 * A re-found device used to arrive here looking exactly like a brand-new host:
 * `StatePill` special-cased only `conflict`, so `matched` rendered the same
 * amber "New" badge, and the row sat in the queue waiting for the same manual
 * Accept the device had already been given once. These cases pin the three
 * things that changed — the pill tells the truth, the matched device is named,
 * and enrichment is reported instead of being invisible.
 */
import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../api/discovery.js', () => ({
  getPendingResults: vi.fn().mockResolvedValue({ data: [] }),
  getEnrichedResults: vi.fn().mockResolvedValue({ data: [] }),
  mergeResult: vi.fn().mockResolvedValue({ data: {} }),
  enhancedBulkMerge: vi.fn().mockResolvedValue({ data: {} }),
}));

vi.mock('../api/monitor.js', () => ({
  createTargetMonitor: vi.fn().mockResolvedValue({ data: {} }),
}));

vi.mock('../api/client.jsx', () => ({
  default: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  clustersApi: { list: vi.fn().mockResolvedValue([]) },
  networksApi: { list: vi.fn().mockResolvedValue({ data: [] }) },
  deviceRolesApi: {
    list: vi.fn().mockResolvedValue([{ slug: 'server', label: 'Server', rank: 1 }]),
  },
  computeUnitsApi: { list: vi.fn().mockResolvedValue([]) },
}));

vi.mock('../context/AuthContext.jsx', () => ({
  useAuth: () => ({ user: { id: 1 }, token: 'test-token-value-12345' }),
}));

vi.mock('../components/common/Toast', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn(), warn: vi.fn(), info: vi.fn() }),
}));

vi.mock('../utils/logger.js', () => ({
  __esModule: true,
  default: { warn: vi.fn(), error: vi.fn(), info: vi.fn(), debug: vi.fn() },
}));

import ReviewQueuePanel, { describeFilled } from '../components/discovery/ReviewQueuePanel.jsx';
import { getEnrichedResults, getPendingResults, mergeResult } from '../api/discovery.js';

function row(overrides) {
  return {
    id: 1,
    ip_address: '192.168.0.1',
    mac_address: 'F8:5E:42:0A:66:6A',
    hostname: null,
    state: 'new',
    merge_status: 'pending',
    created_at: '2026-09-06T00:00:00Z',
    ...overrides,
  };
}

const renderPanel = () =>
  render(
    <MemoryRouter>
      <ReviewQueuePanel />
    </MemoryRouter>
  );

beforeEach(() => {
  vi.clearAllMocks();
  getPendingResults.mockResolvedValue({ data: [] });
  getEnrichedResults.mockResolvedValue({ data: [] });
});

describe('the state pill', () => {
  it.each([
    ['new', 'New'],
    ['matched', 'Known'],
    ['conflict', 'Conflict'],
  ])('renders %s as "%s"', async (state, label) => {
    getPendingResults.mockResolvedValue({ data: [row({ state })] });
    renderPanel();
    expect(await screen.findByText(label)).toBeInTheDocument();
  });

  it('degrades an unrecognised state to New rather than rendering nothing', async () => {
    getPendingResults.mockResolvedValue({ data: [row({ state: 'something-new-later' })] });
    renderPanel();
    expect(await screen.findByText('New')).toBeInTheDocument();
  });

  it('names the device a matched row was tied to', async () => {
    getPendingResults.mockResolvedValue({
      data: [
        row({
          state: 'matched',
          matched_entity_type: 'hardware',
          matched_entity_id: 8,
          matched_entity_name: '_gateway',
        }),
      ],
    });
    renderPanel();
    expect(await screen.findByText(/_gateway/)).toBeInTheDocument();
  });
});

describe('the recently-enriched section', () => {
  it('is collapsed by default and shows how many there are', async () => {
    getEnrichedResults.mockResolvedValue({
      data: [
        row({ id: 9, merge_status: 'auto_updated', state: 'matched' }),
        row({ id: 10, merge_status: 'auto_updated', state: 'matched' }),
      ],
    });
    renderPanel();

    expect(await screen.findByText('Recently enriched (2)')).toBeInTheDocument();
    expect(screen.queryByText(/filled MAC/)).not.toBeInTheDocument();
  });

  it('expands to show the device and what was filled in', async () => {
    getEnrichedResults.mockResolvedValue({
      data: [
        row({
          id: 9,
          merge_status: 'auto_updated',
          state: 'matched',
          matched_entity_name: '_gateway',
          enriched_fields_json: JSON.stringify([
            { field: 'mac_address', value: 'F8:5E:42:0A:66:6A' },
            { field: 'vendor', value: 'Acme' },
          ]),
        }),
      ],
    });
    renderPanel();

    fireEvent.click(await screen.findByText('Recently enriched (1)'));

    expect(await screen.findByText('_gateway')).toBeInTheDocument();
    expect(screen.getByText('filled MAC, vendor')).toBeInTheDocument();
  });

  it('says what happened when there was nothing left to fill', async () => {
    getEnrichedResults.mockResolvedValue({
      data: [
        row({
          id: 9,
          merge_status: 'auto_updated',
          state: 'matched',
          matched_entity_name: 'complete-device',
          enriched_fields_json: '[]',
        }),
      ],
    });
    renderPanel();

    fireEvent.click(await screen.findByText('Recently enriched (1)'));

    expect(await screen.findByText('refreshed last seen')).toBeInTheDocument();
  });

  it('does not blank the review queue when the enriched fetch fails', async () => {
    getPendingResults.mockResolvedValue({ data: [row({ ip_address: '192.168.0.66' })] });
    getEnrichedResults.mockRejectedValue(new Error('boom'));
    renderPanel();

    expect(await screen.findByText('192.168.0.66')).toBeInTheDocument();

    fireEvent.click(screen.getByText('Recently enriched (0)'));
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('Could not load enriched devices')
    );
  });
});

describe('describeFilled', () => {
  it('names each filled field in plain words', () => {
    expect(
      describeFilled(JSON.stringify([{ field: 'mac_address' }, { field: 'os_version' }]))
    ).toBe('filled MAC, OS');
  });

  it.each([null, undefined, '[]', 'not json'])(
    'falls back to the liveness wording for %s',
    (value) => {
      expect(describeFilled(value)).toBe('refreshed last seen');
    }
  );

  it('passes an unknown field name through rather than dropping it', () => {
    expect(describeFilled(JSON.stringify([{ field: 'future_column' }]))).toBe(
      'filled future_column'
    );
  });
});

describe('accepting a row for a device that already exists', () => {
  const matched = row({
    state: 'matched',
    matched_entity_type: 'hardware',
    matched_entity_id: 8,
    matched_entity_name: '_gateway',
  });

  it('renders a drawer body instead of nothing at all', async () => {
    getPendingResults.mockResolvedValue({ data: [matched] });
    renderPanel();

    fireEvent.click(await screen.findByText('192.168.0.1'));

    expect(await screen.findByText('Known Device')).toBeInTheDocument();
    expect(await screen.findByText(/already on the map/i)).toBeInTheDocument();
  });

  it('sends no name or role from the row action, so the device is not renamed', async () => {
    // `merge_scan_result` applies overrides with a blanket setattr, and the
    // row's name default is the discovered hostname or the bare IP — so this
    // used to rename an existing device to its own IP address and reset its
    // role to "server".
    getPendingResults.mockResolvedValue({ data: [matched] });
    renderPanel();

    fireEvent.click(await screen.findByTitle('Accept'));

    await waitFor(() => expect(mergeResult).toHaveBeenCalled());
    const [, payload] = mergeResult.mock.calls.at(-1);
    expect(payload.action).toBe('accept');
    expect(payload.overrides).not.toHaveProperty('name');
    expect(payload.overrides).not.toHaveProperty('role');
  });

  it('still sends a name and role for a genuinely new host', async () => {
    getPendingResults.mockResolvedValue({ data: [row({ state: 'new' })] });
    renderPanel();

    fireEvent.click(await screen.findByTitle('Accept'));

    await waitFor(() => expect(mergeResult).toHaveBeenCalled());
    const [, payload] = mergeResult.mock.calls.at(-1);
    expect(payload.overrides.name).toBe('192.168.0.1');
    expect(payload.overrides.role).toBe('server');
  });

  it('sends no name or role from the drawer either', async () => {
    getPendingResults.mockResolvedValue({ data: [matched] });
    renderPanel();

    fireEvent.click(await screen.findByText('192.168.0.1'));
    await screen.findByText('Known Device');
    // Three buttons answer to "Accept": the toolbar's (disabled while nothing
    // is selected), the row's icon button, and the drawer's. The drawer is
    // rendered last, so it is the last in DOM order.
    const accepts = screen.getAllByRole('button', { name: /^accept$/i });
    fireEvent.click(accepts.at(-1));

    await waitFor(() => expect(mergeResult).toHaveBeenCalled());
    const [, payload] = mergeResult.mock.calls.at(-1);
    expect(payload.overrides).not.toHaveProperty('name');
    expect(payload.overrides).not.toHaveProperty('role');
  });
});
