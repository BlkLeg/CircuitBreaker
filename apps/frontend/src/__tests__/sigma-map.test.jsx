/**
 * SigmaMap is a renderer: it draws the document it is given.
 *
 * It previously fetched its own topology with `format: 'sigma'` — a format the
 * backend never implemented — so `Graph.import` rejected the ordinary payload
 * with "serialized node is missing its key", the catch swallowed it, and the
 * canvas came up empty. These tests hold the boundary: no request, and the
 * graph it builds is the one it was handed.
 */
import { render } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import SigmaMap from '../components/map/SigmaMap';
import { graphApi } from '../api/client';

vi.mock('../api/client', () => ({ graphApi: { topology: vi.fn() } }));

const imported = [];
vi.mock('graphology', () => ({
  default: class {
    constructor(opts) {
      this.opts = opts;
      this.order = 0;
    }
    import(data) {
      imported.push({ opts: this.opts, data });
    }
    nodes() {
      return [];
    }
    setNodeAttribute() {}
    hasNodeAttribute() {
      return true;
    }
  },
}));

vi.mock('sigma', () => ({
  default: class {
    refresh() {}
    kill() {}
  },
}));

vi.mock('graphology-layout-forceatlas2', () => ({ default: { assign: vi.fn() } }));

const NODES = [
  { id: 'a', position: { x: 1, y: 2 }, data: { label: 'nas-01' } },
  { id: 'b', position: { x: 3, y: 4 }, data: { label: 'sw-01' } },
];
const EDGES = [{ id: 'e1', source: 'a', target: 'b', data: { relation: 'connected_to' } }];

beforeEach(() => {
  imported.length = 0;
  vi.clearAllMocks();
});

describe('SigmaMap', () => {
  it('never requests topology of its own', () => {
    render(<SigmaMap nodes={NODES} edges={EDGES} />);

    expect(graphApi.topology).not.toHaveBeenCalled();
  });

  it('imports the nodes and edges it was given', () => {
    render(<SigmaMap nodes={NODES} edges={EDGES} />);

    expect(imported).toHaveLength(1);
    expect(imported[0].data.nodes.map((n) => n.key)).toEqual(['a', 'b']);
    expect(imported[0].data.edges.map((e) => e.key)).toEqual(['e1']);
  });

  it('builds a multi graph, so parallel edges cannot throw', () => {
    render(<SigmaMap nodes={NODES} edges={EDGES} />);

    expect(imported[0].opts).toMatchObject({ multi: true });
  });

  it('renders an empty document without throwing', () => {
    expect(() => render(<SigmaMap nodes={[]} edges={[]} />)).not.toThrow();
  });
});
