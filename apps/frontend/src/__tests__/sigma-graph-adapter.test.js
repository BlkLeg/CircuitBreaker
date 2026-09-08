/**
 * Canonical map graph -> graphology serialization for the Sigma renderer.
 *
 * SigmaMap used to fetch `format: 'sigma'`, a format the backend never
 * implemented, and hand the ordinary topology payload to `Graph.import` —
 * which rejects it with "serialized node is missing its key". The renderer now
 * draws the same document React Flow draws, so this conversion is where the
 * two renderers agree.
 */
import { describe, expect, it } from 'vitest';
import Graph from 'graphology';
import { toSigmaGraph } from '../utils/graphAdapter';

// A multi graph, matching SigmaMap: nothing in the map document prevents two
// edges between the same pair (an auto-discovered relation and an ad-hoc link,
// say), and a simple graph throws on the second one.
const newGraph = () => new Graph({ multi: true });

const node = (id, over = {}) => ({
  id,
  position: { x: 10, y: 20 },
  data: { label: `label-${id}`, glowColor: '#abcdef' },
  ...over,
});

describe('toSigmaGraph', () => {
  it('produces something graphology can import', () => {
    const serialized = toSigmaGraph(
      [node('a'), node('b')],
      [{ id: 'e1', source: 'a', target: 'b', data: { relation: 'connected_to' } }]
    );

    const g = newGraph();
    expect(() => g.import(serialized)).not.toThrow();
    expect(g.order).toBe(2);
    expect(g.size).toBe(1);
  });

  it('carries the label, saved position and colour onto each node', () => {
    const g = newGraph();
    g.import(toSigmaGraph([node('a')], []));

    expect(g.getNodeAttributes('a')).toMatchObject({
      label: 'label-a',
      x: 10,
      y: 20,
      color: '#abcdef',
    });
  });

  it('drops edges whose endpoints are not in the graph', () => {
    // Filters can hide a node while its edges remain in the document; importing
    // a dangling edge throws and takes the whole render down.
    const serialized = toSigmaGraph([node('a')], [{ id: 'e1', source: 'a', target: 'ghost' }]);

    const g = newGraph();
    expect(() => g.import(serialized)).not.toThrow();
    expect(g.size).toBe(0);
  });

  it('skips hidden nodes and the edges that referenced them', () => {
    const serialized = toSigmaGraph(
      [node('a'), node('b', { hidden: true })],
      [{ id: 'e1', source: 'a', target: 'b' }]
    );

    const g = newGraph();
    g.import(serialized);
    expect(g.order).toBe(1);
    expect(g.size).toBe(0);
  });

  it('tolerates a duplicate edge between the same pair', () => {
    const serialized = toSigmaGraph(
      [node('a'), node('b')],
      [
        { id: 'e1', source: 'a', target: 'b' },
        { id: 'e2', source: 'a', target: 'b' },
      ]
    );

    const g = newGraph();
    expect(() => g.import(serialized)).not.toThrow();
  });

  it('falls back to the node id when it has no label', () => {
    const g = newGraph();
    g.import(toSigmaGraph([{ id: 'bare', position: { x: 0, y: 0 }, data: {} }], []));

    expect(g.getNodeAttribute('bare', 'label')).toBe('bare');
  });

  it('gives a node without a position deterministic coordinates', () => {
    const g = newGraph();
    g.import(toSigmaGraph([{ id: 'a', data: {} }], []));

    expect(Number.isFinite(g.getNodeAttribute('a', 'x'))).toBe(true);
    expect(Number.isFinite(g.getNodeAttribute('a', 'y'))).toBe(true);
  });
});
