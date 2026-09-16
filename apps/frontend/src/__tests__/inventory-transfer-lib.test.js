import { describe, expect, it } from 'vitest';
import {
  ASSET_KINDS,
  buildResolutions,
  countRecords,
  decisionKey,
  defaultDecisionFor,
  describeDecision,
  exportFileName,
  formatSnapshotSize,
  incomingRow,
  isRelationKind,
  isResolvable,
  proposedRenameValue,
  referenceTargetKind,
  sumCounts,
  toResolution,
} from '../lib/inventoryTransfer';

const DOCUMENT = {
  entities: {
    services: [{ id: 5, name: 'paperless', slug: 'paperless', hardware_id: 999 }],
    hardware: [{ id: 1, name: 'pve-01' }],
  },
  relationships: {
    service_dependencies: [{ service_id: 5, depends_on_id: 404, connection_type: 'http' }],
  },
};

describe('inventoryTransfer lib', () => {
  it('counts records across grouped maps', () => {
    expect(countRecords(DOCUMENT.entities)).toBe(2);
    expect(countRecords(DOCUMENT.relationships)).toBe(1);
    expect(sumCounts({ services: 2, tags: 3 })).toBe(5);
    expect(sumCounts(null)).toBe(0);
  });

  it('declares the seven counted asset kinds', () => {
    expect(ASSET_KINDS).toHaveLength(7);
    expect(ASSET_KINDS).not.toContain('docs');
    expect(ASSET_KINDS).not.toContain('tags');
  });

  it('finds the incoming row a conflict points at — entities by id, relations by position', () => {
    expect(incomingRow(DOCUMENT, 'services', 5)?.slug).toBe('paperless');
    expect(incomingRow(DOCUMENT, 'service_dependencies', 1)?.connection_type).toBe('http');
    expect(incomingRow(DOCUMENT, 'services', 99)).toBeNull();
    expect(isRelationKind('service_dependencies')).toBe(true);
    expect(isRelationKind('services')).toBe(false);
  });

  it('resolves which kind a reference field targets, including attachments', () => {
    expect(referenceTargetKind('services', 'hardware_id')).toBe('hardware');
    expect(referenceTargetKind('service_dependencies', 'depends_on_id')).toBe('services');
    expect(referenceTargetKind('entity_tags', 'entity_id', { entity_type: 'compute_unit' })).toBe(
      'compute_units'
    );
    expect(referenceTargetKind('entity_tags', 'tag_id')).toBe('tags');
    expect(referenceTargetKind('services', 'nonsense')).toBeNull();
  });

  it('proposes a suffix rename and keeps decisions addressable', () => {
    expect(proposedRenameValue({ slug: 'grafana' }, 'slug')).toBe('grafana-imported');
    expect(proposedRenameValue(null, 'slug')).toBe('record-imported');
    expect(decisionKey('services', 7, null)).toBe('services:7:identity');
    expect(decisionKey('services', 7, 'hardware_id')).toBe('services:7:hardware_id');
  });

  it('turns decisions into backend resolutions', () => {
    expect(toResolution('services', 7, { action: 'match', targetId: 3 })).toEqual({
      entity_type: 'services',
      source_id: 7,
      action: 'match',
      target_id: 3,
    });
    expect(toResolution('services', 7, { action: 'rename', newValue: 'grafana-lab' })).toEqual({
      entity_type: 'services',
      source_id: 7,
      action: 'rename',
      new_value: 'grafana-lab',
    });
    expect(
      toResolution('services', 7, { action: 'reassign', field: 'hardware_id', targetId: 2 })
    ).toEqual({
      entity_type: 'services',
      source_id: 7,
      action: 'reassign',
      field: 'hardware_id',
      target_id: 2,
    });
    expect(toResolution('services', 7, { action: null })).toBeNull();
  });

  it('builds the resolutions array only from complete decisions', () => {
    const decisions = {
      'services:7:identity': { action: 'rename', newValue: 'x', kind: 'services', sourceId: 7 },
      'services:8:identity': { action: null, kind: 'services', sourceId: 8 },
      'services:9:hardware_id': {
        action: 'reassign',
        field: 'hardware_id',
        targetId: 4,
        kind: 'services',
        sourceId: 9,
      },
    };
    expect(buildResolutions(decisions)).toEqual([
      { entity_type: 'services', source_id: 7, action: 'rename', new_value: 'x' },
      {
        entity_type: 'services',
        source_id: 9,
        action: 'reassign',
        field: 'hardware_id',
        target_id: 4,
      },
    ]);
  });

  it('defaults to rename for identity clashes and reassign for missing references, never to a match', () => {
    const identity = defaultDecisionFor(
      {
        entity_type: 'services',
        source_id: 5,
        reason_code: 'unique_identity_conflict',
        field: 'slug',
      },
      DOCUMENT
    );
    expect(identity.action).toBe('rename');
    expect(identity.newValue).toBe('paperless-imported');

    const missing = defaultDecisionFor(
      {
        entity_type: 'services',
        source_id: 5,
        reason_code: 'missing_reference',
        field: 'hardware_id',
      },
      DOCUMENT
    );
    expect(missing.action).toBe('reassign');
    expect(missing.field).toBe('hardware_id');
    expect(missing.targetId).toBeNull();
  });

  it('describes a saved decision in one line', () => {
    expect(describeDecision({ action: 'rename', newValue: 'grafana-lab' })).toBe(
      'Create as “grafana-lab”'
    );
    expect(describeDecision({ action: 'match', targetId: 9, targetLabel: 'pve-01' })).toBe(
      'Match existing pve-01'
    );
    expect(
      describeDecision({
        action: 'reassign',
        field: 'hardware_id',
        targetId: 9,
        targetLabel: 'docker-01',
      })
    ).toBe('Set hardware_id to docker-01');
  });

  it('knows which conflicts the UI can settle and which need a revised file', () => {
    expect(isResolvable('unique_identity_conflict')).toBe(true);
    expect(isResolvable('missing_reference')).toBe(true);
    expect(isResolvable('unsupported_reference_type')).toBe(false);
  });

  it('formats snapshot sizes and export filenames honestly', () => {
    expect(formatSnapshotSize(42.816)).toBe('42.82 MB');
    expect(formatSnapshotSize(0.001)).toBe('< 0.01 MB');
    expect(formatSnapshotSize(2048)).toBe('2.0 GB');
    expect(formatSnapshotSize(null)).toBeNull();
    expect(exportFileName(new Date('2026-09-10T12:00:00Z'))).toBe(
      'circuit-breaker-inventory-2026-09-10.json'
    );
  });
});
