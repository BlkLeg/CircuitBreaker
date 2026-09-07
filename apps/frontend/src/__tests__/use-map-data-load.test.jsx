/**
 * Request behavior of useMapDataLoad: response ordering and what re-issues a
 * topology fetch.
 *
 * Switching map, environment, included types or Cloud View re-issues the
 * topology request. Without a request-generation guard a slow earlier response
 * can resolve after a newer one and overwrite the canvas with stale data.
 */
import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { useMapDataLoad } from '../hooks/useMapDataLoad';
import { graphApi } from '../api/client';
import { groupNodesIntoCloud } from '../utils/cloudView';

vi.mock('../utils/cloudView', () => ({
  groupNodesIntoCloud: vi.fn((nodes) => nodes),
  restoreFromCloudView: vi.fn((nodes) => nodes),
}));

vi.mock('../api/client', () => ({
  graphApi: {
    topology: vi.fn(),
    getLayout: vi.fn().mockResolvedValue({ data: { layout_data: null } }),
    placeNode: vi.fn(),
  },
  clustersApi: {},
  hardwareApi: {},
  computeUnitsApi: {},
  servicesApi: {},
  storageApi: {},
  networksApi: {},
  miscApi: {},
  externalNodesApi: {},
}));

const topologyOf = (nodeId) => ({
  data: {
    nodes: [
      {
        id: nodeId,
        label: nodeId,
        type: 'hardware',
        role: 'server',
        tags: [],
        ref_id: 1,
      },
    ],
    edges: [],
  },
});

function makeArgs(overrides = {}) {
  const setNodes = vi.fn();
  return {
    args: {
      mapId: 1,
      setLoading: vi.fn(),
      setError: vi.fn(),
      setEdgeMode: vi.fn(),
      setEdgeLabelVisible: vi.fn(),
      setNodeSpacing: vi.fn(),
      setGroupBy: vi.fn(),
      setLastSaved: vi.fn(),
      setBoundaries: vi.fn(),
      setMapLabels: vi.fn(),
      setVisualLines: vi.fn(),
      setEdgeOverrides: vi.fn(),
      setNodes,
      setEdges: vi.fn(),
      setLayoutEngine: vi.fn(),
      edgeOverridesRef: { current: {} },
      autoPlacedIdsRef: { current: new Set() },
      placingNodesRef: { current: false },
      pendingPlacementCountRef: { current: 0 },
      batchPlacedCountRef: { current: 0 },
      saveLayoutRef: { current: vi.fn() },
      hasRestoredViewport: { current: true },
      unmountedRef: { current: false },
      containerRef: { current: null },
      fitView: vi.fn(),
      setViewport: vi.fn(),
      cloudViewEnabled: false,
      isMobile: false,
      showLabels: true,
      settings: {},
      envFilter: null,
      includeTypes: new Map([['hardware', true]]),
      getLayoutName: () => 'default',
      toast: { error: vi.fn(), success: vi.fn(), warn: vi.fn() },
      ...overrides,
    },
    setNodes,
  };
}

const nodeIdsOf = (setNodes) =>
  setNodes.mock.calls
    .map(([arg]) => arg)
    .filter(Array.isArray)
    .map((nodes) => nodes.map((n) => n.id));

beforeEach(() => {
  vi.clearAllMocks();
  graphApi.getLayout.mockResolvedValue({ data: { layout_data: null } });
});

describe('useMapDataLoad request ordering', () => {
  it('ignores a stale topology response that resolves after a newer one', async () => {
    let resolveFirst;
    graphApi.topology
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveFirst = () => resolve(topologyOf('stale-node'));
          })
      )
      .mockImplementationOnce(() => Promise.resolve(topologyOf('fresh-node')));

    const { args, setNodes } = makeArgs();
    const { result } = renderHook(() => useMapDataLoad(args));

    let firstCall;
    await act(async () => {
      firstCall = result.current.fetchData();
      await result.current.fetchData();
    });

    await waitFor(() => expect(nodeIdsOf(setNodes).flat()).toContain('fresh-node'));

    // The older request now resolves last.
    await act(async () => {
      resolveFirst();
      await firstCall;
    });

    expect(nodeIdsOf(setNodes).flat()).not.toContain('stale-node');
  });

  it('applies the response when only one request is in flight', async () => {
    graphApi.topology.mockResolvedValue(topologyOf('only-node'));

    const { args, setNodes } = makeArgs();
    const { result } = renderHook(() => useMapDataLoad(args));

    await act(async () => {
      await result.current.fetchData();
    });

    await waitFor(() => expect(nodeIdsOf(setNodes).flat()).toContain('only-node'));
  });
});

describe('useMapDataLoad Cloud View', () => {
  it('does not re-issue a topology request when Cloud View is toggled', () => {
    graphApi.topology.mockResolvedValue(topologyOf('n1'));
    const { args } = makeArgs({ cloudViewEnabled: false });

    const { result, rerender } = renderHook((props) => useMapDataLoad(props), {
      initialProps: args,
    });
    const before = result.current.fetchData;

    rerender({ ...args, cloudViewEnabled: true });

    // MapPage runs `useEffect(() => { fetchData(); }, [fetchData])`, so a new
    // identity here is a second full topology fetch racing the in-place
    // transform the toggle already performs.
    expect(result.current.fetchData).toBe(before);
  });

  it('still groups nodes into the cloud when Cloud View is on at fetch time', async () => {
    graphApi.topology.mockResolvedValue(topologyOf('n1'));
    const { args } = makeArgs({ cloudViewEnabled: true });
    const { result } = renderHook(() => useMapDataLoad(args));

    await act(async () => {
      await result.current.fetchData();
    });

    expect(groupNodesIntoCloud).toHaveBeenCalled();
  });

  it('does not group nodes when Cloud View is off', async () => {
    graphApi.topology.mockResolvedValue(topologyOf('n1'));
    const { args } = makeArgs({ cloudViewEnabled: false });
    const { result } = renderHook(() => useMapDataLoad(args));

    await act(async () => {
      await result.current.fetchData();
    });

    expect(groupNodesIntoCloud).not.toHaveBeenCalled();
  });
});
