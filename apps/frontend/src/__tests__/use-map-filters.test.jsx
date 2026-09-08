/**
 * Map filter ownership: query inputs (environment, entity types) and
 * client-side visibility (tag, hardware role) kept together, per the map
 * rework doc's "extract filters as one unit".
 */
import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { useMapFilters } from '../hooks/useMapFilters';
import { environmentsApi, settingsApi } from '../api/client';

vi.mock('../api/client', () => ({
  environmentsApi: { list: vi.fn() },
  settingsApi: { update: vi.fn() },
}));

const ENVS = [
  { id: 1, name: 'prod' },
  { id: 2, name: 'lab' },
];

function makeArgs(overrides = {}) {
  return {
    settings: null,
    setNodes: vi.fn(),
    setEdges: vi.fn(),
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  environmentsApi.list.mockResolvedValue({ data: ENVS });
  settingsApi.update.mockResolvedValue({});
});

describe('useMapFilters', () => {
  it('includes every entity type except docker by default', () => {
    const { result } = renderHook(() => useMapFilters(makeArgs()));

    const include = result.current.includeTypes;
    expect(include.get('hardware')).toBe(true);
    expect(include.get('service')).toBe(true);
    expect(include.get('docker')).toBe(false);
  });

  it('loads the environments list for the filter dropdown', async () => {
    const { result } = renderHook(() => useMapFilters(makeArgs()));

    await waitFor(() => expect(result.current.environmentsList).toEqual(ENVS));
  });

  it('survives an environments list failure', async () => {
    environmentsApi.list.mockRejectedValue(new Error('offline'));
    const { result } = renderHook(() => useMapFilters(makeArgs()));

    await waitFor(() => expect(environmentsApi.list).toHaveBeenCalled());
    expect(result.current.environmentsList).toEqual([]);
  });

  it('applies the default environment from settings once the list arrives', async () => {
    const { result } = renderHook(() =>
      useMapFilters(makeArgs({ settings: { default_environment: 'lab' } }))
    );

    await waitFor(() => expect(result.current.envFilter).toBe(2));
  });

  it('does not re-apply the default environment over a later user choice', async () => {
    const { result } = renderHook(() =>
      useMapFilters(makeArgs({ settings: { default_environment: 'lab' } }))
    );
    await waitFor(() => expect(result.current.envFilter).toBe(2));

    act(() => result.current.setEnvFilter(''));

    // The guard ref means the settings effect must not fight the user.
    await waitFor(() => expect(result.current.envFilter).toBe(''));
  });

  it('recomputes node visibility from tag and hardware role together', async () => {
    const args = makeArgs();
    const { result } = renderHook(() => useMapFilters(args));

    act(() => {
      result.current.setDebouncedTag('nas');
      result.current.setHwRoleFilter('server');
    });

    await waitFor(() => expect(args.setNodes).toHaveBeenCalled());
    const updater = args.setNodes.mock.calls.at(-1)[0];
    const out = updater([
      { id: 'a', originalType: 'hardware', _tags: ['nas'], _hwRole: 'server' },
      { id: 'b', originalType: 'hardware', _tags: ['nas'], _hwRole: 'switch' },
      { id: 'c', originalType: 'hardware', _tags: ['other'], _hwRole: 'server' },
    ]);

    expect(out.map((n) => n.hidden)).toEqual([false, true, true]);
  });

  it('persists the include map and reports the save transition', async () => {
    const { result } = renderHook(() => useMapFilters(makeArgs()));

    await act(async () => {
      await result.current.handleSaveFilters();
    });

    expect(settingsApi.update).toHaveBeenCalledWith({
      map_default_filters: { include: expect.objectContaining({ hardware: true, docker: false }) },
    });
    expect(result.current.filterSaved).toBe(true);
    expect(result.current.filterSaving).toBe(false);
  });

  it('does not surface a filter-save failure as an error state', async () => {
    settingsApi.update.mockRejectedValue(new Error('nope'));
    const { result } = renderHook(() => useMapFilters(makeArgs()));

    await act(async () => {
      await result.current.handleSaveFilters();
    });

    expect(result.current.filterSaving).toBe(false);
    expect(result.current.filterSaved).toBe(false);
  });

  it('restores saved default include filters from settings', async () => {
    const { result } = renderHook(() =>
      useMapFilters(makeArgs({ settings: { map_default_filters: { include: { docker: true } } } }))
    );

    await waitFor(() => expect(result.current.includeTypes.get('docker')).toBe(true));
    expect(result.current.includeTypes.get('hardware')).toBe(true);
  });

  it('does not re-apply saved defaults over a later user change', async () => {
    const settings = { map_default_filters: { include: { docker: true } } };
    const { result, rerender } = renderHook(() => useMapFilters(makeArgs({ settings })));
    await waitFor(() => expect(result.current.includeTypes.get('docker')).toBe(true));

    act(() => result.current.setIncludeTypes((m) => new Map(m).set('docker', false)));
    rerender();

    expect(result.current.includeTypes.get('docker')).toBe(false);
  });
});
