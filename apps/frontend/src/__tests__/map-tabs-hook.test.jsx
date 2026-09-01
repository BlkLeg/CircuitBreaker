import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

vi.mock('../api/maps', () => ({
  mapsApi: {
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
  },
}));

import { mapsApi } from '../api/maps';
import { useMapTabs } from '../hooks/useMapTabs';

function Probe() {
  const { maps, activeMapId, loading, error, retry } = useMapTabs();
  return (
    <div>
      <span data-testid="loading">{String(loading)}</span>
      <span data-testid="error">{error ? 'yes' : 'no'}</span>
      <span data-testid="active">{String(activeMapId)}</span>
      <span data-testid="count">{maps.length}</span>
      <button onClick={retry}>retry</button>
    </div>
  );
}

const EXISTING_MAPS = [
  { id: 1, name: 'Main' },
  { id: 2, name: 'Rack Room' },
];

describe('useMapTabs', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it('loads the existing map list and picks an active id', async () => {
    mapsApi.list.mockResolvedValue(EXISTING_MAPS);

    render(<Probe />);

    await waitFor(() => expect(screen.getByTestId('loading').textContent).toBe('false'));
    expect(screen.getByTestId('error').textContent).toBe('no');
    expect(screen.getByTestId('count').textContent).toBe('2');
    expect(screen.getByTestId('active').textContent).toBe('1');
  });

  it('bootstraps a "Main" map when the list comes back empty', async () => {
    mapsApi.list.mockResolvedValue([]);
    mapsApi.create.mockResolvedValue({ id: 9, name: 'Main' });

    render(<Probe />);

    await waitFor(() => expect(screen.getByTestId('loading').textContent).toBe('false'));
    expect(mapsApi.create).toHaveBeenCalledWith('Main');
    expect(screen.getByTestId('error').textContent).toBe('no');
    expect(screen.getByTestId('count').textContent).toBe('1');
    expect(screen.getByTestId('active').textContent).toBe('9');
  });

  // Regression test for the wedge: previously there was no .catch anywhere in
  // the hook, so a rejected list() left loading stuck at true forever with no
  // error state and no way to escape short of a full page reload.
  it('sets loading false and an error when list() rejects, instead of hanging forever', async () => {
    mapsApi.list.mockRejectedValue(new Error('network down'));

    render(<Probe />);

    await waitFor(() => expect(screen.getByTestId('loading').textContent).toBe('false'));
    expect(screen.getByTestId('error').textContent).toBe('yes');
    expect(screen.getByTestId('active').textContent).toBe('null');
  });

  it('sets loading false and an error when the empty-list bootstrap create() rejects', async () => {
    mapsApi.list.mockResolvedValue([]);
    mapsApi.create.mockRejectedValue(new Error('server exploded'));

    render(<Probe />);

    await waitFor(() => expect(screen.getByTestId('loading').textContent).toBe('false'));
    expect(screen.getByTestId('error').textContent).toBe('yes');
    expect(screen.getByTestId('active').textContent).toBe('null');
  });

  it('retry() clears the error and re-requests the map list', async () => {
    mapsApi.list.mockRejectedValueOnce(new Error('network down'));
    mapsApi.list.mockResolvedValueOnce(EXISTING_MAPS);

    render(<Probe />);

    await waitFor(() => expect(screen.getByTestId('error').textContent).toBe('yes'));

    fireEvent.click(screen.getByText('retry'));

    await waitFor(() => expect(screen.getByTestId('error').textContent).toBe('no'));
    await waitFor(() => expect(screen.getByTestId('loading').textContent).toBe('false'));
    expect(mapsApi.list).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId('count').textContent).toBe('2');
  });

  it('does not set state when list() rejects after the component has unmounted', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
    let rejectList;
    mapsApi.list.mockReturnValue(
      new Promise((_resolve, reject) => {
        rejectList = reject;
      })
    );

    const { unmount } = render(<Probe />);
    unmount();

    rejectList(new Error('too late'));
    // Flush the microtask queue so the rejection handler (if it ran) would
    // have called setState by now.
    await Promise.resolve();
    await Promise.resolve();

    // No React "state update on an unmounted component" warning was logged.
    expect(consoleError).not.toHaveBeenCalled();
    consoleError.mockRestore();
  });
});
