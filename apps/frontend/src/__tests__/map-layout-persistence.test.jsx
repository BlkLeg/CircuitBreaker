/**
 * Regression contract for map layout persistence.
 *
 * Locks the save -> store -> parse round-trip and the legacy flat-layout
 * compatibility path before that logic moves behind a versioned layout codec.
 * `parseLayoutData` is the only reader of stored layouts and had no coverage;
 * a self-hoster's saved map is the thing these tests protect.
 */
import { act, renderHook } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { parseLayoutData } from '../utils/mapGeometryUtils';
import { useMapMutations } from '../hooks/useMapMutations';
import { graphApi } from '../api/client';

vi.mock('../api/client', () => ({
  clustersApi: { delete: vi.fn() },
  hardwareApi: { delete: vi.fn() },
  computeUnitsApi: { delete: vi.fn() },
  servicesApi: { delete: vi.fn() },
  storageApi: { delete: vi.fn() },
  networksApi: { delete: vi.fn() },
  miscApi: { delete: vi.fn() },
  externalNodesApi: { delete: vi.fn() },
  graphApi: { saveLayout: vi.fn().mockResolvedValue({}) },
}));

beforeEach(() => {
  vi.clearAllMocks();
});

describe('parseLayoutData — legacy flat layouts', () => {
  it('treats a bare node-position map as the nodes document', () => {
    const legacy = { 'hw-1': { x: 10, y: 20 }, 'svc-2': { x: 30, y: 40 } };

    const parsed = parseLayoutData(legacy);

    expect(parsed.nodes).toEqual(legacy);
    expect(parsed.edges).toEqual({});
    expect(parsed.boundaries).toEqual([]);
    expect(parsed.labels).toEqual([]);
    expect(parsed.visualLines).toEqual([]);
  });

  it('applies view defaults for a legacy layout that has none', () => {
    const parsed = parseLayoutData({ 'hw-1': { x: 0, y: 0 } });

    expect(parsed.edgeMode).toBe('smoothstep');
    expect(parsed.edgeLabelVisible).toBe(true);
    expect(parsed.nodeSpacing).toBe(1);
    expect(parsed.groupBy).toBe('none');
  });
});

describe('parseLayoutData — structured layouts', () => {
  const structured = {
    nodes: { 'hw-1': { x: 1, y: 2 } },
    nodeShapes: { 'hw-1': 'circle' },
    edges: { 'e-1': { sourceSide: 'left' } },
    boundaries: [{ id: 'b-1', name: 'Rack', memberIds: ['hw-1'] }],
    labels: [{ id: 'l-1', text: 'Closet' }],
    visualLines: [{ id: 'v-1', lineType: 'fiber' }],
    edgeMode: 'straight',
    edgeLabelVisible: false,
    nodeSpacing: 2,
    groupBy: 'environment',
  };

  it('preserves every stored section', () => {
    const parsed = parseLayoutData(structured);

    expect(parsed.nodes).toEqual(structured.nodes);
    expect(parsed.nodeShapes).toEqual(structured.nodeShapes);
    expect(parsed.edges).toEqual(structured.edges);
    expect(parsed.boundaries).toEqual(structured.boundaries);
    expect(parsed.labels).toEqual(structured.labels);
    expect(parsed.visualLines).toEqual(structured.visualLines);
  });

  it('preserves view options, including a falsy edgeLabelVisible', () => {
    const parsed = parseLayoutData(structured);

    expect(parsed.edgeMode).toBe('straight');
    expect(parsed.nodeSpacing).toBe(2);
    expect(parsed.groupBy).toBe('environment');
    // `?? true`, not `|| true` — a user who hid edge labels keeps them hidden.
    expect(parsed.edgeLabelVisible).toBe(false);
  });

  it('parses an equivalent JSON string identically to the object', () => {
    expect(parseLayoutData(JSON.stringify(structured))).toEqual(parseLayoutData(structured));
  });

  it('coerces a non-array visualLines to an empty array', () => {
    const parsed = parseLayoutData({ ...structured, visualLines: { bogus: true } });

    expect(parsed.visualLines).toEqual([]);
  });
});

function makeSaveArgs(overrides = {}) {
  return {
    mapId: 3,
    nodesRef: {
      current: [
        { id: 'hw-1', position: { x: 1, y: 2 }, data: { nodeShape: 'circle' } },
        { id: 'svc-2', position: { x: 3, y: 4 }, data: {} },
      ],
    },
    edgeOverridesRef: { current: { 'e-1': { sourceSide: 'left' } } },
    mapLabelsRef: { current: [{ id: 'l-1', text: 'Closet', flow: { x: 0, y: 0 } }] },
    visualLinesRef: {
      current: [
        { id: 'v-1', startFlow: { x: 0, y: 0 }, endFlow: { x: 5, y: 5 }, lineType: 'fiber' },
      ],
    },
    dirtyRef: { current: true },
    boundaries: [
      { id: 'b-1', name: 'Rack', memberIds: ['hw-1'], flowRect: { minX: 0 } },
      { id: 'boundary-docker-auto-9', name: 'docker', memberIds: [], flowRect: { minX: 0 } },
    ],
    edgeMode: 'straight',
    edgeLabelVisible: false,
    nodeSpacing: 2,
    groupBy: 'environment',
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
    toast: { error: vi.fn(), success: vi.fn(), warn: vi.fn() },
    ...overrides,
  };
}

async function saveAndParse(args) {
  const { result } = renderHook(() => useMapMutations(args));
  await act(async () => {
    await result.current.saveLayoutSnapshot();
  });
  const [, serialized, mapId] = graphApi.saveLayout.mock.calls[0];
  return { parsed: parseLayoutData(serialized), mapId };
}

describe('layout save -> parse round-trip', () => {
  it('round-trips positions, shapes, edge overrides, lines and view options', async () => {
    const args = makeSaveArgs();

    const { parsed, mapId } = await saveAndParse(args);

    expect(mapId).toBe(3);
    expect(parsed.nodes).toEqual({ 'hw-1': { x: 1, y: 2 }, 'svc-2': { x: 3, y: 4 } });
    expect(parsed.nodeShapes).toEqual({ 'hw-1': 'circle' });
    expect(parsed.edges).toEqual({ 'e-1': { sourceSide: 'left' } });
    expect(parsed.visualLines).toEqual([
      { id: 'v-1', startFlow: { x: 0, y: 0 }, endFlow: { x: 5, y: 5 }, lineType: 'fiber' },
    ]);
    expect(parsed.edgeMode).toBe('straight');
    expect(parsed.edgeLabelVisible).toBe(false);
    expect(parsed.nodeSpacing).toBe(2);
    expect(parsed.groupBy).toBe('environment');
  });

  it('excludes auto-generated docker boundaries from the saved document', async () => {
    const { parsed } = await saveAndParse(makeSaveArgs());

    expect(parsed.boundaries.map((b) => b.id)).toEqual(['b-1']);
  });

  it('clears the dirty flag and records a save timestamp', async () => {
    const args = makeSaveArgs();

    await saveAndParse(args);

    expect(args.dirtyRef.current).toBe(false);
    expect(args.setLastSaved).toHaveBeenCalledWith(expect.any(String));
  });
});
