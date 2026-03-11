/* eslint-disable security/detect-object-injection -- internal node/type keys */
/**
 * Pure data transformation helpers for the topology map.
 * No React dependencies — safe to import from any module.
 */

import { ENTITY_FIELDS } from '../components/map/mapConstants';
import { validateIpAddress } from './validation';
import { servicesApi, computeUnitsApi, storageApi } from '../api/client';

// ── Node data transformations ────────────────────────────────────────────────

export function applyTelemetryUpdate(current, nodeId, res) {
  return current.map((cn) => {
    if (cn.id !== nodeId) return cn;
    return {
      ...cn,
      data: {
        ...cn.data,
        telemetry_status: res.status || 'unknown',
        telemetry_data: res.data || null,
        telemetry_last_polled: res.last_polled || null,
      },
    };
  });
}

export function applyMonitorUpdates(current, monitors) {
  const byHwId = {};
  monitors.forEach((m) => {
    byHwId[m.hardware_id] = m;
  });
  return current.map((cn) => {
    if (cn.originalType !== 'hardware') return cn;
    const m = byHwId[cn._refId];
    if (!m) return cn;
    return {
      ...cn,
      data: {
        ...cn.data,
        monitor_enabled: m.enabled ?? true,
        monitor_id: m.id ?? null,
        monitor_status: m.last_status ?? null,
        monitor_latency_ms: m.latency_ms ?? null,
        monitor_last_checked_at: m.last_checked_at ?? null,
        monitor_uptime_pct_24h: m.uptime_pct_24h ?? null,
      },
    };
  });
}

export function buildRelatedNodes(nodeId, nodesArr, edgesArr) {
  const related = [];
  edgesArr.forEach((edge) => {
    if (edge.source === nodeId) {
      const target = nodesArr.find((node) => node.id === edge.target);
      if (target)
        related.push({ direction: 'out', relation: edge._relation || edge.label, node: target });
    } else if (edge.target === nodeId) {
      const source = nodesArr.find((node) => node.id === edge.source);
      if (source)
        related.push({ direction: 'in', relation: edge._relation || edge.label, node: source });
    }
  });
  return related;
}

export function buildNodeSysinfoRows(node) {
  const type = node?.originalType;
  if (!type) return [];

  const fields = ENTITY_FIELDS[type] || [];
  return fields
    .map((field) => {
      const rawValue = node?.data?.[field.key];
      if (rawValue == null || rawValue === '') return null;
      const rendered = typeof field.fmt === 'function' ? field.fmt(rawValue) : String(rawValue);
      if (!rendered || rendered === '—') return null;
      return {
        key: field.key,
        label: field.label,
        value: rendered,
      };
    })
    .filter(Boolean);
}

export function buildNodeStatusDetails(node) {
  const modelStatus = node?.data?.status || null;
  const overrideStatus = node?.data?.status_override || null;
  const telemetryStatus = node?.data?.telemetry_status || null;
  const telemetryLastPolled = node?.data?.telemetry_last_polled || null;

  const effectiveStatus =
    overrideStatus && overrideStatus !== 'auto'
      ? overrideStatus
      : modelStatus || telemetryStatus || 'unknown';

  return {
    effectiveStatus,
    modelStatus,
    overrideStatus,
    telemetryStatus,
    telemetryLastPolled,
  };
}

/**
 * Proxmox cluster = many hypervisors + VMs. Used for kiosk-style centering on hypervisor nodes.
 */
export function proxmoxClusterDetected(nodes) {
  if (!Array.isArray(nodes) || nodes.length === 0) return false;
  const hypervisorCount = nodes.filter((n) => n.data?.role === 'hypervisor').length;
  return hypervisorCount > 5;
}

export function getNodeRank(node) {
  const type = node.originalType || node.data?.originalType;
  switch (type) {
    case 'external':
      return 0;
    case 'network':
      return 1;
    case 'cluster':
      return 2;
    case 'hardware':
      return 3;
    case 'compute':
      return 4;
    case 'service':
      return 5;
    case 'storage':
    case 'misc':
      return 6;
    default:
      return 5;
  }
}

// ── Docker boundary grouping ─────────────────────────────────────────────────

/**
 * Auto-generates transient boundaries that group docker containers (and their
 * directly-connected docker networks) by shared host (compute_id / hardware_id).
 * IDs are prefixed with "boundary-docker-auto-" so they are excluded from
 * layout snapshots and always regenerated fresh from the current node state.
 */
export function groupDockerIntoBoundaries(rfNodes, rfEdges, savedBoundaries) {
  const groups = new Map();
  for (const n of rfNodes) {
    if (n.originalType !== 'docker_container') continue;
    const hostKey = n.data.compute_id
      ? `cu-${n.data.compute_id}`
      : n.data.hardware_id
        ? `hw-${n.data.hardware_id}`
        : null;
    if (!hostKey) continue;
    if (!groups.has(hostKey)) groups.set(hostKey, { ids: new Set(), name: null });
    groups.get(hostKey).ids.add(n.id);
  }
  if (groups.size === 0) return [];

  const containerHostMap = new Map();
  for (const [hostKey, group] of groups) {
    for (const id of group.ids) containerHostMap.set(id, hostKey);
  }

  const dockerNetworkIds = new Set(
    rfNodes.filter((n) => n.originalType === 'docker_network').map((n) => n.id)
  );
  for (const e of rfEdges) {
    const srcKey = containerHostMap.get(e.source);
    const tgtKey = containerHostMap.get(e.target);
    if (srcKey && dockerNetworkIds.has(e.target)) groups.get(srcKey).ids.add(e.target);
    if (tgtKey && dockerNetworkIds.has(e.source)) groups.get(tgtKey).ids.add(e.source);
  }

  for (const [, group] of groups) {
    for (const nodeId of group.ids) {
      const n = rfNodes.find((x) => x.id === nodeId && x.originalType === 'docker_container');
      if (!n?.data?.docker_labels) continue;
      try {
        const labels =
          typeof n.data.docker_labels === 'string'
            ? JSON.parse(n.data.docker_labels)
            : n.data.docker_labels;
        const project = labels?.['com.docker.compose.project'];
        if (project) {
          group.name = project;
          break;
        }
      } catch {
        /* unparseable labels — ignore */
      }
    }
  }

  const autoBoundaries = [];
  for (const [hostKey, group] of groups) {
    const memberIds = [...group.ids];
    if (memberIds.length < 2) continue;

    const boundaryId = `boundary-docker-auto-${hostKey}`;
    if (savedBoundaries.some((b) => b.id === boundaryId)) continue;
    const userCovered = savedBoundaries.some(
      (b) =>
        !b.id?.startsWith('boundary-docker-auto-') &&
        Array.isArray(b.memberIds) &&
        memberIds.filter((id) => b.memberIds.includes(id)).length >= Math.ceil(memberIds.length / 2)
    );
    if (userCovered) continue;

    autoBoundaries.push({
      id: boundaryId,
      name: group.name || 'Docker Stack',
      memberIds,
      flowRect: null,
      color: '#1cb8d8',
      fillOpacity: 0.04,
      shape: 'rectangle',
    });
  }
  return autoBoundaries;
}

// ── Bulk create helpers ──────────────────────────────────────────────────────

export function slugifyName(name) {
  return String(name || '')
    .trim()
    .toLowerCase()
    .replaceAll(/[^a-z0-9]+/g, '-')
    .replaceAll(/^-+|-+$/g, '');
}

export function makeBulkRow(mode, defaults = {}) {
  const rowId = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  if (mode === 'compute') {
    return {
      id: rowId,
      name: '',
      kind: defaults.kind || 'vm',
      ip_address: '',
      os: '',
      icon_slug: '',
    };
  }
  if (mode === 'storage') {
    return {
      id: rowId,
      name: '',
      kind: 'disk',
      capacity_gb: '',
      path: '',
      protocol: '',
      icon_slug: '',
    };
  }
  return {
    id: rowId,
    name: '',
    port: '',
    protocol: 'tcp',
    status: 'running',
    ip_address: '',
    url: '',
    icon_slug: '',
  };
}

export function buildBulkServicePayload(row, initialValues) {
  const payload = {
    name: row.name.trim(),
    slug: slugifyName(row.name),
    status: row.status || 'running',
    url: row.url?.trim() || null,
    ip_address: row.ip_address?.trim() || null,
    icon_slug: row.icon_slug?.trim() || null,
    description: null,
    tags: [],
  };

  if (row.port) {
    payload.ports = [
      {
        port: Number.parseInt(row.port, 10),
        protocol: row.protocol || 'tcp',
      },
    ];
  }

  const runsOn = initialValues?.runs_on;
  if (runsOn?.startsWith('hw_')) {
    payload.hardware_id = Number.parseInt(runsOn.slice(3), 10);
    payload.compute_id = null;
  } else if (runsOn?.startsWith('cu_')) {
    payload.compute_id = Number.parseInt(runsOn.slice(3), 10);
    payload.hardware_id = null;
  }

  return payload;
}

export function buildBulkComputePayload(row, initialValues) {
  return {
    name: row.name.trim(),
    kind: row.kind || 'vm',
    hardware_id: initialValues?.hardware_id || null,
    ip_address: row.ip_address?.trim() || null,
    os: row.os || null,
    icon_slug: row.icon_slug?.trim() || null,
  };
}

export function buildBulkStoragePayload(row, initialValues) {
  return {
    name: row.name.trim(),
    kind: row.kind || 'disk',
    capacity_gb: row.capacity_gb === '' ? null : Number(row.capacity_gb),
    path: row.path?.trim() || null,
    protocol: row.protocol?.trim() || null,
    icon_slug: row.icon_slug?.trim() || null,
    hardware_id: initialValues?.hardware_id || null,
  };
}

export function validateBulkRows(mode, rows) {
  const errors = {};
  rows.forEach((row) => {
    if (!row.name?.trim()) {
      errors[row.id] = 'Name is required.';
      return;
    }
    if (mode === 'service') {
      if (row.port && Number.isNaN(Number.parseInt(row.port, 10))) {
        errors[row.id] = 'Port must be a number.';
        return;
      }
      const ipErr = validateIpAddress(row.ip_address || '');
      if (ipErr) errors[row.id] = ipErr;
    }
    if (mode === 'compute') {
      const ipErr = validateIpAddress(row.ip_address || '');
      if (ipErr) errors[row.id] = ipErr;
    }
  });
  return errors;
}

export async function runBulkCreate(mode, rows, initialValues) {
  const failed = [];
  let successCount = 0;

  for (const row of rows) {
    try {
      if (mode === 'service') {
        await servicesApi.create(buildBulkServicePayload(row, initialValues));
      } else if (mode === 'compute') {
        await computeUnitsApi.create(buildBulkComputePayload(row, initialValues));
      } else if (mode === 'storage') {
        await storageApi.create(buildBulkStoragePayload(row, initialValues));
      }
      successCount += 1;
    } catch (err) {
      failed.push({
        rowId: row.id,
        name: row.name || 'Unnamed',
        message: err?.message || 'Create failed',
      });
    }
  }

  return { successCount, failed };
}

export function getServiceDefaults(targetNode) {
  if (!targetNode?._refId) return {};
  if (targetNode.originalType === 'compute') return { runs_on: `cu_${targetNode._refId}` };
  if (targetNode.originalType === 'hardware') return { runs_on: `hw_${targetNode._refId}` };
  return {};
}

export function getComputeDefaults(targetNode, kindHint) {
  const defaults = {};
  if (kindHint) defaults.kind = kindHint;
  if (targetNode?.originalType === 'hardware' && targetNode._refId)
    defaults.hardware_id = targetNode._refId;
  return defaults;
}

export function getStorageDefaults(targetNode) {
  if (targetNode?.originalType === 'hardware' && targetNode._refId) {
    return { hardware_id: targetNode._refId };
  }
  return {};
}

export function getDefaultQuickCreateValues(mode, targetNode, kindHint = null) {
  if (mode === 'service') return getServiceDefaults(targetNode);
  if (mode === 'compute') return getComputeDefaults(targetNode, kindHint);
  if (mode === 'storage') return getStorageDefaults(targetNode);
  return {};
}
