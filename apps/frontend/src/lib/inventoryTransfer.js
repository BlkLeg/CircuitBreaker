/**
 * Pure helpers for the Inventory transfer workbench.
 *
 * Decision vocabulary, reference maps, and count derivations live here so the
 * UI and tests share one contract (docs/design/approved-ui/02-inventory-transfer.md).
 * The backend revalidates every rule these mirrors encode; nothing here is a
 * security boundary.
 */

/** Mirrors the backend's bounded document limits (format.py). */
export const MAX_DOCUMENT_BYTES = 5 * 1024 * 1024;
export const MAX_DOCUMENT_LABEL = '5 MiB';

/** The seven asset kinds the summary tile counts; docs, tags and clusters are
 * portable data, not assets. Mirror of services/inventory_transfer/summary.py. */
export const ASSET_KINDS = Object.freeze([
  'hardware',
  'compute_units',
  'services',
  'storage',
  'networks',
  'misc_items',
  'external_nodes',
]);

export const ASSET_KIND_LABELS = Object.freeze({
  hardware: 'hardware',
  compute_units: 'compute units',
  services: 'services',
  storage: 'storage',
  networks: 'networks',
  misc_items: 'misc items',
  external_nodes: 'external nodes',
});

/** Conflict reason codes → what the UI offers for them. */
export const CONFLICT_LABELS = Object.freeze({
  unique_identity_conflict: 'Name already used locally',
  duplicate_source_identity: 'Duplicate inside this file',
  missing_reference: 'Missing parent or reference',
  match_not_found: 'Chosen match no longer exists',
  unsupported_reference_type: 'Attachment type is not portable',
});

/** Reasons the operator can settle in this UI; everything else means the source
 * inventory has to be revised, and the UI must say so rather than hide it. */
export const RESOLVABLE_REASONS = Object.freeze([
  'unique_identity_conflict',
  'duplicate_source_identity',
  'missing_reference',
  'match_not_found',
]);

export function isResolvable(reasonCode) {
  return RESOLVABLE_REASONS.includes(reasonCode);
}

/** One line that says what a saved decision will do. */
export function describeDecision(decision) {
  if (!decision?.action) return 'No decision yet.';
  const targetLabel =
    decision.targetLabel ?? (decision.targetId != null ? `record #${decision.targetId}` : '');
  if (decision.action === 'rename') return `Create as “${decision.newValue}”`;
  if (decision.action === 'match') return `Match existing ${targetLabel}`;
  return `Set ${decision.field} to ${targetLabel}`;
}

/** Mirrors of the backend reference tables (plan.py). Used to pick the local
 * asset kind a reassign decision targets; the backend revalidates. */
export const INTERNAL_REFS = Object.freeze({
  compute_units: { hardware_id: 'hardware' },
  storage: { hardware_id: 'hardware' },
  services: { hardware_id: 'hardware', compute_id: 'compute_units' },
  networks: { gateway_hardware_id: 'hardware' },
});

export const RELATION_REFS = Object.freeze({
  service_dependencies: { service_id: 'services', depends_on_id: 'services' },
  service_storage: { service_id: 'services', storage_id: 'storage' },
  service_misc: { service_id: 'services', misc_id: 'misc_items' },
  hardware_networks: { hardware_id: 'hardware', network_id: 'networks' },
  compute_networks: { compute_id: 'compute_units', network_id: 'networks' },
  hardware_connections: { source_hardware_id: 'hardware', target_hardware_id: 'hardware' },
  hardware_cluster_members: { cluster_id: 'hardware_clusters', hardware_id: 'hardware' },
  external_node_networks: { external_node_id: 'external_nodes', network_id: 'networks' },
  service_external_nodes: { service_id: 'services', external_node_id: 'external_nodes' },
});

export const ATTACHMENT_TYPES = Object.freeze({
  hardware: 'hardware',
  compute: 'compute_units',
  compute_unit: 'compute_units',
  service: 'services',
  storage: 'storage',
  network: 'networks',
  misc: 'misc_items',
  misc_item: 'misc_items',
  external: 'external_nodes',
  external_node: 'external_nodes',
});

/** Entity kinds with a declared unique identity field (plan.py _UNIQUE_FIELDS). */
export const UNIQUE_FIELDS = Object.freeze({
  services: 'slug',
  tags: 'name',
  hardware_clusters: 'name',
});

export function isRelationKind(kind) {
  return Boolean(RELATION_REFS[kind] || kind === 'entity_tags' || kind === 'entity_docs');
}

/** The portable entity kind a reference field points at, or null. */
export function referenceTargetKind(ownerKind, field, row) {
  if (INTERNAL_REFS[ownerKind]?.[field]) return INTERNAL_REFS[ownerKind][field];
  if (RELATION_REFS[ownerKind]?.[field]) return RELATION_REFS[ownerKind][field];
  if (ownerKind === 'entity_tags' || ownerKind === 'entity_docs') {
    if (field === 'entity_id') return ATTACHMENT_TYPES[String(row?.entity_type)] ?? null;
    if (field === 'tag_id') return 'tags';
    if (field === 'doc_id') return 'docs';
  }
  return null;
}

export function sumCounts(counts) {
  return Object.values(counts ?? {}).reduce((total, value) => total + (value || 0), 0);
}

export function countRecords(grouped) {
  return Object.values(grouped ?? {}).reduce(
    (total, rows) => total + (Array.isArray(rows) ? rows.length : 0),
    0
  );
}

/** The incoming record a conflict points at — entity rows by id, relationship
 * rows by position. Relationship rows have no id in the portable format. */
export function incomingRow(document, kind, sourceId) {
  if (isRelationKind(kind)) {
    const rows = document?.relationships?.[kind] ?? [];
    return rows[sourceId - 1] ?? null;
  }
  return (document?.entities?.[kind] ?? []).find((row) => row?.id === sourceId) ?? null;
}

export function decisionKey(kind, sourceId, field) {
  return `${kind}:${sourceId}:${field ?? 'identity'}`;
}

/** The value a "keep both" decision proposes; editable in the drawer. */
export function proposedRenameValue(row, field) {
  const base = String(row?.[field] ?? 'record');
  return `${base}-imported`.slice(0, 200);
}

/** One decision → the backend resolution payload it represents. */
export function toResolution(kind, sourceId, decision) {
  if (!decision?.action) return null;
  const base = { entity_type: kind, source_id: sourceId, action: decision.action };
  if (decision.action === 'match') return { ...base, target_id: decision.targetId };
  if (decision.action === 'rename') return { ...base, new_value: decision.newValue };
  return { ...base, field: decision.field, target_id: decision.targetId };
}

/**
 * The default decision for a conflict: keep-both rename for identity clashes,
 * reassign for missing references. Never auto-matches — adopting an existing
 * record is the operator's call, not a default.
 */
export function defaultDecisionFor(conflict, document) {
  const row = incomingRow(document, conflict.entity_type, conflict.source_id);
  const uniqueField = UNIQUE_FIELDS[conflict.entity_type];
  if (conflict.reason_code === 'missing_reference') {
    return { action: 'reassign', field: conflict.field, targetId: null, row };
  }
  if (uniqueField) {
    return {
      action: 'rename',
      newValue: proposedRenameValue(row, conflict.field ?? uniqueField),
      row,
    };
  }
  return { action: null, row };
}

/** Every stored decision → the resolutions array for the next preview call. */
export function buildResolutions(decisions) {
  return Object.entries(decisions ?? {})
    .map(([, decision]) => {
      const resolution = toResolution(decision.kind, decision.sourceId, decision);
      return resolution?.action ? resolution : null;
    })
    .filter(Boolean);
}

export function formatSnapshotSize(sizeMb) {
  if (sizeMb == null) return null;
  if (sizeMb < 0.01) return '< 0.01 MB';
  if (sizeMb >= 1024) return `${(sizeMb / 1024).toFixed(1)} GB`;
  return `${sizeMb.toFixed(2)} MB`;
}

export function exportFileName(date = new Date()) {
  return `circuit-breaker-inventory-${date.toISOString().slice(0, 10)}.json`;
}

export function downloadJsonFile(filename, data) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

/** Stale-preview error codes the UI answers with a re-review path. */
export const STALE_ERROR_CODES = Object.freeze([
  'preview_stale',
  'preview_expired',
  'preview_changed',
]);
