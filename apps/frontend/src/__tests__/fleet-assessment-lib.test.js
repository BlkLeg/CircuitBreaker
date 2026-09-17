import { describe, expect, it } from 'vitest';
import { filterRows, rowKey, sortRows } from '../lib/fleetAssessment';

const row = (over = {}) => ({
  entity_type: 'hardware',
  entity_id: 1,
  name: 'nas-01',
  state: 'completed',
  reason_code: 'completed',
  identity: {
    vendor: 'acme',
    product: 'widget',
    version: '1.9',
    provenance: 'inventory',
    revision: 0,
  },
  finding_count: 0,
  max_severity: null,
  max_cvss: null,
  completeness: 'complete',
  ...over,
});

describe('sortRows', () => {
  it('leads with the worst severity, not the highest count', () => {
    const rows = [
      row({ entity_id: 1, name: 'many-lows', max_severity: 'low', finding_count: 40 }),
      row({ entity_id: 2, name: 'one-critical', max_severity: 'critical', finding_count: 1 }),
    ];

    expect(sortRows(rows).map((r) => r.name)).toEqual(['one-critical', 'many-lows']);
  });

  it('breaks ties on type and id so the order never wobbles between loads', () => {
    const rows = [
      row({ entity_type: 'service', entity_id: 9, name: 'same' }),
      row({ entity_type: 'hardware', entity_id: 9, name: 'same' }),
    ];

    expect(sortRows(rows).map((r) => r.entity_type)).toEqual(['hardware', 'service']);
    expect(sortRows([...rows].reverse()).map((r) => r.entity_type)).toEqual([
      'hardware',
      'service',
    ]);
  });
});

describe('filterRows', () => {
  const rows = [
    row({
      entity_id: 1,
      name: 'nas-01',
      state: 'completed',
      finding_count: 2,
      max_severity: 'high',
    }),
    row({ entity_id: 2, name: 'mystery', state: 'unassessed', reason_code: 'identity_missing' }),
    row({ entity_id: 3, name: 'old-feed', state: 'stale', finding_count: 1, max_severity: 'low' }),
  ];

  it('finds the entities that cannot be assessed at all', () => {
    const found = filterRows(rows, { stateFilter: 'needs_identity' });

    expect(found.map((r) => r.name)).toEqual(['mystery']);
  });

  it('matches the product as well as the name', () => {
    const found = filterRows(rows, { query: 'widget' });

    expect(found).toHaveLength(3);
  });

  it('never hides an unassessed row behind a severity floor', () => {
    const found = filterRows(rows, { minSeverity: 'high' });

    expect(found.map((r) => r.name)).toEqual(['nas-01', 'mystery']);
  });
});

describe('rowKey', () => {
  it('distinguishes a hardware and a service sharing an id', () => {
    expect(rowKey(row({ entity_type: 'hardware', entity_id: 5 }))).not.toEqual(
      rowKey(row({ entity_type: 'service', entity_id: 5 }))
    );
  });
});
