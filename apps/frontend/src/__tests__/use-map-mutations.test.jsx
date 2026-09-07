import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { useMapMutations } from '../hooks/useMapMutations';
import { hardwareApi, servicesApi } from '../api/client';

vi.mock('../api/client', () => ({
  clustersApi: { delete: vi.fn().mockResolvedValue({}) },
  hardwareApi: { delete: vi.fn().mockResolvedValue({}) },
  computeUnitsApi: { delete: vi.fn().mockResolvedValue({}) },
  servicesApi: { delete: vi.fn().mockResolvedValue({}) },
  storageApi: { delete: vi.fn().mockResolvedValue({}) },
  networksApi: { delete: vi.fn().mockResolvedValue({}) },
  miscApi: { delete: vi.fn().mockResolvedValue({}) },
  externalNodesApi: { delete: vi.fn().mockResolvedValue({}) },
  graphApi: { saveLayout: vi.fn().mockResolvedValue({}) },
}));

function makeArgs(overrides = {}) {
  const nodes = [
    { id: 'hw-1', originalType: 'hardware', _refId: 42, data: { label: 'NAS' }, position: {} },
    { id: 'svc-1', originalType: 'service', _refId: 7, data: { label: 'Plex' }, position: {} },
    { id: 'ghost-1', originalType: 'nonsense', _refId: 9, data: { label: 'Ghost' }, position: {} },
  ];
  const toast = { error: vi.fn(), success: vi.fn(), warn: vi.fn() };
  return {
    mapId: 1,
    nodesRef: { current: nodes },
    edgeOverridesRef: { current: {} },
    mapLabelsRef: { current: [] },
    visualLinesRef: { current: [] },
    dirtyRef: { current: false },
    boundaries: [],
    edgeMode: 'smoothstep',
    edgeLabelVisible: true,
    nodeSpacing: 1,
    groupBy: 'none',
    setLastSaved: vi.fn(),
    setError: vi.fn(),
    setConfirmState: vi.fn(),
    setDeleteConflictModal: vi.fn(),
    setSelectedNode: vi.fn(),
    edges: [],
    deleteConflictModal: { open: false },
    selectedNodeId: null,
    getLayoutName: () => 'default',
    fetchData: vi.fn(),
    toast,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('useMapMutations delete path', () => {
  it('resolves the entity deleter and opens the confirm dialog for a supported type', () => {
    const args = makeArgs();
    const { result } = renderHook(() => useMapMutations(args));

    act(() => {
      result.current.handleDeleteNodeAction('hw-1');
    });

    expect(args.toast.error).not.toHaveBeenCalled();
    expect(args.setConfirmState).toHaveBeenCalledWith(
      expect.objectContaining({ open: true, message: expect.stringContaining('NAS') })
    );
  });

  it('calls the entity delete API with the ref id when confirmed', async () => {
    const args = makeArgs();
    const { result } = renderHook(() => useMapMutations(args));

    act(() => {
      result.current.handleDeleteNodeAction('svc-1');
    });

    const { onConfirm } = args.setConfirmState.mock.calls[0][0];
    await act(async () => {
      await onConfirm();
    });

    expect(servicesApi.delete).toHaveBeenCalledWith(7);
    expect(args.fetchData).toHaveBeenCalled();
  });

  it('reports unsupported for a node type with no registered deleter', () => {
    const args = makeArgs();
    const { result } = renderHook(() => useMapMutations(args));

    act(() => {
      result.current.handleDeleteNodeAction('ghost-1');
    });

    expect(args.toast.error).toHaveBeenCalledWith('Delete is not supported for this node type.');
    expect(args.setConfirmState).not.toHaveBeenCalled();
  });

  it('force-remove resolves the entity deleter for a supported type', async () => {
    const args = makeArgs({
      deleteConflictModal: {
        open: true,
        nodeId: 'hw-1',
        nodeRefId: 42,
        nodeType: 'hardware',
        nodeLabel: 'NAS',
      },
    });
    const { result } = renderHook(() => useMapMutations(args));

    await act(async () => {
      await result.current.forceRemoveDeleteConflicts();
    });

    await waitFor(() => expect(hardwareApi.delete).toHaveBeenCalledWith(42));
    expect(args.toast.error).not.toHaveBeenCalled();
  });
});
