/**
 * API topology -> canonical map graph.
 *
 * This transform was inline in `useMapDataLoad`, between an await and a dozen
 * setState calls, so none of it could be exercised without driving the whole
 * hook. It is pure: response in, nodes and edges out.
 */
import { describe, expect, it } from 'vitest';
import { adaptTopology } from '../features/map/model/graphAdapter';

const INCLUDE_ALL = new Map([
  ['cluster', true],
  ['hardware', true],
]);

const node = (over = {}) => ({
  id: 'hardware-1',
  label: 'nas-01',
  type: 'hardware',
  role: 'server',
  tags: ['nas'],
  ref_id: 7,
  ...over,
});

const adapt = (data, opts = {}) =>
  adaptTopology(data, {
    showLabels: true,
    includeTypes: INCLUDE_ALL,
    uplinkOverrides: {},
    ...opts,
  });

describe('adaptTopology — nodes', () => {
  it('builds a React Flow node shell from an API node', () => {
    const { nodes } = adapt({ nodes: [node()], edges: [] });

    expect(nodes[0]).toMatchObject({
      id: 'hardware-1',
      type: 'iconNode',
      originalType: 'hardware',
      position: { x: 0, y: 0 },
      _tags: ['nas'],
      _refId: 7,
      _hwRole: 'server',
    });
    expect(nodes[0].data).toMatchObject({ label: 'nas-01', type: 'hardware', role: 'server' });
  });

  it('carries the hardware role only for hardware nodes', () => {
    const { nodes } = adapt({ nodes: [node({ type: 'service', role: 'server' })], edges: [] });

    expect(nodes[0]._hwRole).toBe(null);
  });

  it('marks switches with a class the stylesheet keys off', () => {
    const { nodes } = adapt({ nodes: [node({ role: 'switch' })], edges: [] });

    expect(nodes[0].className).toBe('node-switch');
  });

  it('hides cluster nodes when clusters are filtered out', () => {
    const clusters = new Map([['cluster', false]]);
    const { nodes } = adapt(
      { nodes: [node({ type: 'cluster' })], edges: [] },
      {
        includeTypes: clusters,
      }
    );

    expect(nodes[0].hidden).toBe(true);
  });

  it('defaults absent collections rather than leaving them undefined', () => {
    const { nodes } = adapt({ nodes: [node({ tags: undefined, ports: undefined })], edges: [] });

    expect(nodes[0]._tags).toEqual([]);
    expect(nodes[0].data.ports).toEqual([]);
    expect(nodes[0].data.docs).toEqual([]);
    expect(nodes[0].data.telemetry_status).toBe('unknown');
  });

  it('flags docker entities', () => {
    const { nodes } = adapt({ nodes: [node({ type: 'docker_container' })], edges: [] });

    expect(nodes[0].data.is_docker).toBe(true);
  });
});

describe('adaptTopology — edges', () => {
  const edge = (over = {}) => ({
    id: 'e-1',
    source: 'hardware-1',
    target: 'hardware-2',
    relation: 'connected_to',
    ...over,
  });

  it('builds a smart edge carrying its relation', () => {
    const { edges } = adapt({ nodes: [], edges: [edge()] });

    expect(edges[0]).toMatchObject({ id: 'e-1', type: 'smart', _relation: 'connected_to' });
  });

  it('suppresses edge labels when labels are off', () => {
    const { edges } = adapt({ nodes: [], edges: [edge()] }, { showLabels: false });

    expect(edges[0].label).toBe('');
    expect(edges[0].data.label).toBe('');
  });

  it('animates only dependency and runs relations', () => {
    const { edges } = adapt({
      nodes: [],
      edges: [edge({ relation: 'depends_on' }), edge({ id: 'e-2', relation: 'connected_to' })],
    });

    expect(edges.map((e) => e.animated)).toEqual([true, false]);
  });
});

describe('adaptTopology — cross-cutting', () => {
  it('marks both endpoints of a cluster_member edge as cluster members', () => {
    const { nodes } = adapt({
      nodes: [node({ id: 'a' }), node({ id: 'b' }), node({ id: 'c' })],
      edges: [{ id: 'e-1', source: 'a', target: 'b', relation: 'cluster_member' }],
    });

    const members = Object.fromEntries(nodes.map((n) => [n.id, n.data.isClusterMember]));
    expect(members).toEqual({ a: true, b: true, c: false });
  });

  it('applies a configured uplink override to the matching node', () => {
    const { nodes } = adapt(
      { nodes: [node({ id: 'a' }), node({ id: 'b' })], edges: [] },
      { uplinkOverrides: { a: 2500 } }
    );

    expect(nodes[0].data).toMatchObject({
      uplinkSpeed: 2500,
      upload_speed_mbps: 2500,
      download_speed_mbps: 2500,
    });
    expect(nodes[1].data.uplinkSpeed).toBeUndefined();
  });

  it('ignores a non-numeric uplink override', () => {
    const { nodes } = adapt(
      { nodes: [node({ id: 'a' })], edges: [] },
      {
        uplinkOverrides: { a: 'fast' },
      }
    );

    expect(nodes[0].data.uplinkSpeed).toBeUndefined();
  });
});
