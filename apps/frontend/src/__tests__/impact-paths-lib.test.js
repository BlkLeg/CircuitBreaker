import { describe, expect, it } from 'vitest';
import {
  buildNameIndex,
  describeCompleteness,
  describeEmpty,
  edgeLabel,
  graphLayout,
  pathSteps,
} from '../lib/impactPaths';

const RESULT = {
  root_asset: { asset_type: 'hardware', asset_id: 3, name: 'pve-01', status: 'online' },
  impacted_hardware: [],
  impacted_compute_units: [
    { asset_type: 'compute_unit', asset_id: 7, name: 'vm-postgres', status: 'running' },
  ],
  impacted_services: [{ asset_type: 'service', asset_id: 11, name: 'nextcloud', status: 'up' }],
  impacted_storage: [],
  total_impact_count: 2,
  summary: 'If pve-01 goes offline, 2 downstream assets lose availability.',
  paths: [
    {
      asset: { asset_type: 'service', asset_id: 11, name: 'nextcloud', status: 'up' },
      edges: [
        {
          identity: 'e1',
          provider_type: 'hardware',
          provider_id: 3,
          dependent_type: 'compute_unit',
          dependent_id: 7,
          edge_type: 'hosting',
          provenance: 'confirmed',
          source_kind: 'compute_units.hardware_id',
          source_id: 7,
          label: 'hosted by',
        },
        {
          identity: 'e2',
          provider_type: 'compute_unit',
          provider_id: 7,
          dependent_type: 'service',
          dependent_id: 11,
          edge_type: 'hosting',
          provenance: 'confirmed',
          source_kind: 'services.compute_id',
          source_id: 11,
          label: 'runs on',
        },
      ],
      provenance: 'confirmed',
    },
  ],
  edges: [],
  connectivity: [],
  evaluated_at: '2026-09-15T12:00:00Z',
  completeness: 'complete',
  truncation_reason: null,
  limits: { max_nodes: 500, max_depth: 12, max_edges: 5000 },
  inferred_available: false,
};

describe('edgeLabel', () => {
  it('prefers the server label and falls back to the type', () => {
    expect(edgeLabel({ label: 'runs on', edge_type: 'hosting' })).toBe('runs on');
    expect(edgeLabel({ edge_type: 'connectivity' })).toBe('connects to');
    expect(edgeLabel(null)).toBe('');
  });
});

describe('describeCompleteness', () => {
  it('returns null for a complete traversal', () => {
    expect(describeCompleteness(RESULT)).toBeNull();
    expect(describeCompleteness(null)).toBeNull();
  });

  it('discloses every truncation reason the backend emits', () => {
    for (const reason of ['node_limit', 'depth_limit', 'edge_limit']) {
      const view = describeCompleteness({
        ...RESULT,
        completeness: 'truncated',
        truncation_reason: reason,
      });
      expect(view.reason).toBe(reason);
      expect(view.detail).toMatch(/not of the whole graph|not included/i);
    }
  });

  it('still discloses an unknown truncation reason as partial', () => {
    const view = describeCompleteness({
      ...RESULT,
      completeness: 'truncated',
      truncation_reason: 'something_new',
    });
    expect(view.detail).toMatch(/stopped early/i);
  });
});

describe('describeEmpty', () => {
  it('an untruncated zero result is a real answer — no caveat needed from the lib', () => {
    expect(describeEmpty({ ...RESULT, total_impact_count: 0 })).toBeNull();
  });

  it('a truncated zero result must not read as proof of no dependents', () => {
    const view = describeEmpty({
      ...RESULT,
      total_impact_count: 0,
      completeness: 'truncated',
      truncation_reason: 'node_limit',
    });
    expect(view.title).toMatch(/within the traversed portion/i);
    expect(view.detail).toMatch(/inconclusive/i);
  });
});

describe('pathSteps', () => {
  it('chains a multi-hop path in dependency direction, names resolved', () => {
    const names = buildNameIndex(RESULT);
    const steps = pathSteps(RESULT.paths[0], names);
    expect(steps).toEqual([
      {
        from: 'pve-01',
        to: 'vm-postgres',
        label: 'hosted by',
        edgeType: 'hosting',
        provenance: 'confirmed',
      },
      {
        from: 'vm-postgres',
        to: 'nextcloud',
        label: 'runs on',
        edgeType: 'hosting',
        provenance: 'confirmed',
      },
    ]);
  });

  it('falls back to a typed placeholder for nodes the result does not name', () => {
    const names = new Map();
    const steps = pathSteps(RESULT.paths[0], names);
    expect(steps[0].from).toBe('hardware #3');
  });
});

describe('graphLayout', () => {
  it('layers nodes by path depth and keeps the root first', () => {
    const layout = graphLayout(RESULT);
    expect(layout.nodes[0].isRoot).toBe(true);
    expect(layout.nodes.find((n) => n.name === 'vm-postgres').depth).toBe(1);
    expect(layout.nodes.find((n) => n.name === 'nextcloud').depth).toBe(2);
    expect(layout.columnCount).toBe(3);
  });

  it('returns null for empty or oversized results', () => {
    expect(graphLayout(null)).toBeNull();
    expect(graphLayout({ ...RESULT, total_impact_count: 0 })).toBeNull();
    const wide = {
      ...RESULT,
      impacted_compute_units: Array.from({ length: 41 }, (_, i) => ({
        asset_type: 'compute_unit',
        asset_id: 100 + i,
        name: `vm-${i}`,
        status: null,
      })),
    };
    expect(graphLayout(wide)).toBeNull();
  });
});
