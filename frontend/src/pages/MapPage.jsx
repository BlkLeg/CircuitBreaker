import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { createPortal } from 'react-dom';
import ReactFlow, {
  Background,
  Controls,
  Panel,
  useNodesState,
  useEdgesState,
  ReactFlowProvider,
  useReactFlow,
  useViewport,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { useNavigate } from 'react-router-dom';
import { X } from 'lucide-react';
import { graphApi, hardwareApi, computeUnitsApi, servicesApi, storageApi, networksApi, miscApi, clustersApi, externalNodesApi, telemetryApi, environmentsApi } from '../api/client';
import { getPendingResults } from '../api/discovery.js';
import { useSettings } from '../context/SettingsContext';
import IconPickerModal, { getIconEntry } from '../components/common/IconPickerModal';
import ConfirmDialog from '../components/common/ConfirmDialog';
import FormModal from '../components/common/FormModal';
import { getVendorIcon } from '../icons/vendorIcons';
import ContextMenu from '../components/map/ContextMenu';
import BulkQuickCreateModal from '../components/map/BulkQuickCreateModal';
import CreateNodeModal from '../components/map/CreateNodeModal';
import CustomNode from '../components/map/CustomNode';
import CustomEdge from '../components/map/CustomEdge';
import ConnectionTypePicker from '../components/map/ConnectionTypePicker';
import { discoveryEmitter } from '../hooks/useDiscoveryStream.js';
import { useIsMobile } from '../hooks/useIsMobile';
import WifiOverlay from '../components/map/WifiOverlay';
import Sidebar from '../components/Map/Sidebar';
import { useToast } from '../components/common/Toast';
import { normalizeConnectionType } from '../components/map/connectionTypes';
import { HARDWARE_ROLES } from '../config/hardwareRoles';
import { validateIpAddress } from '../utils/validation';
import { recalculateAllEdges } from '../utils/bandwidthCalculator';
import {
  createLinkByNodeIds,
  inferEdgeNodeIdsFromMeta,
  unlinkByEdge,
} from '../components/map/linkMutations';

// Stable context for passing edge interaction callbacks to SmartEdge without
// re-rendering every edge when the callback ref changes.
export const MapEdgeCallbacksContext = React.createContext({ current: null });

import { getDagreLayout, getForceLayout, getTreeLayout } from '../utils/layouts';
import { groupNodesIntoCloud, restoreFromCloudView } from '../utils/cloudView';

// ── Node Styles ─────────────────────────────────────────────────────────────
const NODE_STYLES = {
  cluster:  { background: '#7c3aed', borderColor: '#5b21b6', glowColor: '#a78bfa' },  // violet
  hardware: { background: '#4a7fa5', borderColor: '#2c5f7a', glowColor: '#4a7fa5' },  // steel blue
  compute:  { background: '#3a7d44', borderColor: '#1f5c2c', glowColor: '#3a7d44' },  // green
  service:  { background: '#c2601e', borderColor: '#8f4012', glowColor: '#e07030' },  // orange
  storage:  { background: '#7b4fa0', borderColor: '#5a3278', glowColor: '#7b4fa0' },  // purple
  network:  { background: '#0e8a8a', borderColor: '#0a6060', glowColor: '#0eb8b8' },  // cyan
  misc:     { background: '#4a5568', borderColor: '#2d3748', glowColor: '#6b7a96' },  // gray
  external: { background: '#2196f3', borderColor: '#1565c0', glowColor: '#64b5f6' },  // sky blue
};

// Per-relation edge accent colours
const EDGE_COLORS = {
  hosts:           '#4a7fa5',
  runs:            '#3a7d44',
  connects_to:     '#0eb8b8',
  depends_on:      '#e07030',
  uses:            '#7b4fa0',
  integrates_with: '#6b7a96',
  routes:          '#ff6b35',
  on_network:      '#00d4aa',
  has_storage:     '#c47a2a',
  cluster_member:  '#a78bfa',
};

const NODE_TYPE_LABELS = {
  cluster: 'Cluster',
  hardware: 'Hardware',
  compute: 'Compute',
  service: 'Service',
  storage: 'Storage',
  network: 'Network',
  misc: 'Misc',
  external: 'External',
};

const CONNECTION_TYPE_LEGEND = [
  { key: 'ethernet', label: '🔌 Ethernet', color: '#32b89e' },
  { key: 'wireless', label: '📶 Wireless', color: '#7c5cbf' },
  { key: 'tunnel', label: '🕳️ Tunnel', color: '#e68161' },
  { key: 'ssh', label: '🛡️ SSH', color: '#32b89e' },
  { key: 'wg', label: '🔒 WireGuard', color: '#c01521' },
  { key: 'vpn', label: '🌐 VPN', color: '#2074c2' },
];

const STATUS_LEGEND = [
  { key: 'active', label: 'Active', color: '#32b89e' },
  { key: 'warning', label: 'Warning', color: '#e68161' },
  { key: 'error', label: 'Error', color: '#ff5459' },
];

// Map node type → page route for "Open in HUD"
const NODE_TYPE_ROUTES = {
  cluster:  '/hardware',
  hardware: '/hardware',
  compute: '/compute-units',
  service: '/services',
  storage: '/storage',
  network: '/networks',
  misc: '/misc',
  external: '/external-nodes',
};

const BASE_NODE_STYLE = {
  background: 'transparent',
  border: 'none',
  boxShadow: 'none',
  padding: 0,
  width: 140,
};

// ── Icon Resolution ──────────────────────────────────────────────────────────

const KIND_ICON = {
  // Storage kinds
  disk:      'hdd',
  pool:      'nas',
  dataset:   'nas',
  share:     'nas',
  // Compute kinds (fallback only — explicit icon_slug takes priority)
  container: 'docker',
};

const ROLE_ICON = {
  router:   'router',
  firewall: 'firewall',
  switch:   'switch',
  ap:       'switch',   // Access Point → same switch icon
  nas:      'nas',
};

function resolveNodeIcon(type, icon_slug, vendor, kind, role) {
  if (icon_slug)                              return getIconEntry(icon_slug)?.path ?? null;
  if (type === 'hardware' && ROLE_ICON[role]) return getIconEntry(ROLE_ICON[role])?.path ?? null;
  if (type === 'hardware' && vendor)          return getVendorIcon(vendor)?.path ?? null;
  if (type === 'network')                     return getIconEntry('network')?.path ?? null;
  if (kind && KIND_ICON[kind])                return getIconEntry(KIND_ICON[kind])?.path ?? null;
  if (type === 'external')                    return getIconEntry('internet')?.path ?? null;
  return null;
}

// ── Module-level pure helpers ───────────────────────────────────────────────

// Omit a single key from an object without leaving an unused variable binding.
function omitKey(obj, key) {
  return Object.fromEntries(Object.entries(obj).filter(([k]) => k !== key));
}

// Tag-hide predicate extracted to avoid exceeding 4 function-nesting depths.
function isHiddenByTag(node, trimmedTag) {
  if (!trimmedTag) return false;
  return !(node._tags || []).some(t => t.toLowerCase().includes(trimmedTag));
}

// Apply a telemetry API response to a node list.
function applyTelemetryUpdate(current, nodeId, res) {
  return current.map(cn => {
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

function getServicePrimaryPort(serviceNode) {
  const directPort = Number(serviceNode?.data?.port);
  if (Number.isFinite(directPort) && directPort > 0) return directPort;

  const ports = serviceNode?.data?.ports;
  if (Array.isArray(ports) && ports.length > 0) {
    const first = ports[0];
    if (typeof first === 'number') return first;
    if (typeof first === 'object' && first?.port != null) {
      const parsed = Number(first.port);
      if (Number.isFinite(parsed) && parsed > 0) return parsed;
    }
  }

  return null;
}

function buildServiceHttpAddress(serviceNode) {
  const ip = serviceNode?.data?.ip_address;
  const port = getServicePrimaryPort(serviceNode);
  if (!ip) return null;
  const portSuffix = port ? `:${port}` : '';
  return `http://${ip}${portSuffix}`;
}

function getHostedServiceRows(hostNode, allNodes, allEdges) {
  const hostIp = hostNode?.data?.ip_address || null;
  const serviceById = new Map(
    allNodes
      .filter((node) => node.originalType === 'service')
      .map((node) => [node.id, node]),
  );

  const rows = [];
  allEdges.forEach((edge) => {
    const relation = edge._relation || edge.data?.relation;
    if (!['runs', 'hosts'].includes(relation)) return;
    if (edge.source !== hostNode.id) return;

    const serviceNode = serviceById.get(edge.target);
    if (!serviceNode) return;

    const serviceIp = serviceNode.data?.ip_address || null;
    const servicePort = getServicePrimaryPort(serviceNode);
    const sameIpAsHost = Boolean(hostIp && serviceIp && hostIp === serviceIp);

    let location = null;
    if (sameIpAsHost && servicePort) {
      location = `:${servicePort}`;
    } else if (serviceIp) {
      location = servicePort ? `${serviceIp}:${servicePort}` : serviceIp;
    } else if (servicePort) {
      location = `:${servicePort}`;
    }

    rows.push({
      id: serviceNode.id,
      name: serviceNode.data?.label || serviceNode.id,
      location,
    });
  });

  return rows;
}

function buildRelatedNodes(nodeId, nodesArr, edgesArr) {
  const related = [];
  edgesArr.forEach((edge) => {
    if (edge.source === nodeId) {
      const target = nodesArr.find((node) => node.id === edge.target);
      if (target) related.push({ direction: 'out', relation: edge._relation || edge.label, node: target });
    } else if (edge.target === nodeId) {
      const source = nodesArr.find((node) => node.id === edge.source);
      if (source) related.push({ direction: 'in', relation: edge._relation || edge.label, node: source });
    }
  });
  return related;
}

function buildNodeSysinfoRows(node) {
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

function buildNodeStatusDetails(node) {
  const modelStatus = node?.data?.status || null;
  const overrideStatus = node?.data?.status_override || null;
  const telemetryStatus = node?.data?.telemetry_status || null;
  const telemetryLastPolled = node?.data?.telemetry_last_polled || null;

  const effectiveStatus = overrideStatus && overrideStatus !== 'auto'
    ? overrideStatus
    : (modelStatus || telemetryStatus || 'unknown');

  return {
    effectiveStatus,
    modelStatus,
    overrideStatus,
    telemetryStatus,
    telemetryLastPolled,
  };
}

// Storage usage bar colour extracted to avoid nested ternaries.
function getBarColor(pct) {
  if (pct >= 85) return 'var(--color-danger)';
  if (pct >= 60) return '#f7c948';
  return 'var(--color-online)';
}

// ── Node rank — used for dagre ordering and debug tooltips ──────────────────
// Lower rank = higher in the hierarchy (closer to root).
function getNodeRank(node) {
  const type = node.originalType || node.data?.originalType;
  switch (type) {
    case 'external': return 0;
    case 'network':  return 1;
    case 'cluster':  return 2;
    case 'hardware': return 3;
    case 'compute':  return 4;
    case 'service':  return 5;
    case 'storage':
    case 'misc':     return 6;
    default:         return 5;
  }
}

// ── Custom Node & Edge types ─────────────────────────────────────────────────
// CustomNode and CustomEdge are defined in components/map/ and registered here.
// Both 'iconNode'/'custom' keys are registered for backward compatibility with
// existing saved layouts and the Phase 1 backend (which emits type:"custom").
const NODE_TYPES = { iconNode: CustomNode, custom: CustomNode };
const EDGE_TYPES = { smart: CustomEdge, custom: CustomEdge };

// ── Entity field definitions for the sidebar ────────────────────────────────
const ENTITY_FIELDS = {
  hardware: [
    { key: 'role',       label: 'Role' },
    { key: 'vendor',     label: 'Vendor' },
    { key: 'model',      label: 'Model' },
    { key: 'ip_address', label: 'IP Address' },
    { key: 'wan_uplink', label: 'WAN / Uplink' },
    { key: 'cpu',        label: 'CPU' },
    { key: 'memory_gb',  label: 'Memory',   fmt: v => `${v} GB` },
    { key: 'location',   label: 'Location' },
    { key: 'notes',      label: 'Notes' },
  ],
  compute: [
    { key: 'kind',       label: 'Kind' },
    { key: 'os',         label: 'OS' },
    { key: 'ip_address', label: 'IP Address' },
    { key: 'cpu_cores',  label: 'CPU Cores' },
    { key: 'memory_mb',  label: 'Memory',  fmt: v => `${v} MB` },
    { key: 'disk_gb',    label: 'Disk',    fmt: v => `${v} GB` },
    { key: 'environment',label: 'Env' },
    { key: 'notes',      label: 'Notes' },
  ],
  service: [
    { key: 'slug',        label: 'Slug' },
    { key: 'category',    label: 'Category' },
    { key: 'status',      label: 'Status' },
    { key: 'ip_address',  label: 'IP Address' },
    { key: 'url',         label: 'URL' },
    { key: 'ports', label: 'Ports', fmt: (v) => Array.isArray(v) ? v.map(p => p.port ? `${p.port}/${p.protocol || 'tcp'}` : '—').filter(Boolean).join(', ') || '—' : String(v ?? '—') },
    { key: 'environment', label: 'Env' },
    { key: 'description', label: 'Description' },
  ],
  storage: [
    { key: 'kind',        label: 'Kind' },
    { key: 'capacity_gb', label: 'Capacity', fmt: v => `${v} GB` },
    { key: 'path',        label: 'Path' },
    { key: 'protocol',    label: 'Protocol' },
    { key: 'notes',       label: 'Notes' },
  ],
  network: [
    { key: 'cidr',        label: 'CIDR' },
    { key: 'vlan_id',     label: 'VLAN ID' },
    { key: 'gateway',     label: 'Gateway' },
    { key: 'description', label: 'Description' },
  ],
  misc: [
    { key: 'kind',        label: 'Kind' },
    { key: 'url',         label: 'URL' },
    { key: 'description', label: 'Description' },
  ],
  cluster: [
    { key: 'description',  label: 'Description' },
    { key: 'environment',  label: 'Env' },
    { key: 'location',     label: 'Location' },
    { key: 'member_count', label: 'Members' },
  ],
  external: [
    { key: 'provider',     label: 'Provider' },
    { key: 'kind',         label: 'Kind' },
    { key: 'region',       label: 'Region' },
    { key: 'ip_address',   label: 'IP Address' },
    { key: 'environment',  label: 'Environment' },
    { key: 'notes',        label: 'Notes' },
  ],
};

const ENTITY_API_GET = {
  cluster:  (id) => clustersApi.get(id),
  hardware: (id) => hardwareApi.get(id),
  compute:  (id) => computeUnitsApi.get(id),
  service:  (id) => servicesApi.get(id),
  storage:  (id) => storageApi.get(id),
  network:  (id) => networksApi.get(id),
  misc:     (id) => miscApi.get(id),
  external: (id) => externalNodesApi.get(id),
};

const ENTITY_API_UPDATE_ICON = {
  hardware: (id, slug) => hardwareApi.update(id, { vendor_icon_slug: slug }),
  compute:  (id, slug) => computeUnitsApi.update(id, { icon_slug: slug }),
  service:  (id, slug) => servicesApi.update(id, { icon_slug: slug }),
  storage:  (id, slug) => storageApi.update(id, { icon_slug: slug }),
  network:  (id, slug) => networksApi.update(id, { icon_slug: slug }),
  misc:     (id, slug) => miscApi.update(id, { icon_slug: slug }),
  external: (id, slug) => externalNodesApi.update(id, { icon_slug: slug }),
};

const ENTITY_API_UPDATE_STATUS = {
  hardware: (id, val) => hardwareApi.update(id, { status_override: val || null }),
  compute:  (id, val) => computeUnitsApi.update(id, { status_override: val || null }),
  service:  (id, val) => servicesApi.update(id, { status: val || 'running' }),
};

const ENTITY_API_UPDATE_ALIAS = {
  cluster:  (id, name) => clustersApi.update(id, { name }),
  hardware: (id, name) => hardwareApi.update(id, { name }),
  compute:  (id, name) => computeUnitsApi.update(id, { name }),
  service:  (id, name) => servicesApi.update(id, { name }),
  storage:  (id, name) => storageApi.update(id, { name }),
  network:  (id, name) => networksApi.update(id, { name }),
  misc:     (id, name) => miscApi.update(id, { name }),
  external: (id, name) => externalNodesApi.update(id, { name }),
};

const ENTITY_API_DELETE = {
  cluster:  (id) => clustersApi.delete(id),
  hardware: (id) => hardwareApi.delete(id),
  compute:  (id) => computeUnitsApi.delete(id),
  service:  (id) => servicesApi.delete(id),
  storage:  (id) => storageApi.delete(id),
  network:  (id) => networksApi.delete(id),
  misc:     (id) => miscApi.delete(id),
  external: (id) => externalNodesApi.delete(id),
};

const STATUS_OPTIONS_BY_TYPE = {
  hardware: ['auto', 'online', 'offline', 'degraded', 'maintenance'],
  compute: ['auto', 'running', 'stopped', 'degraded', 'maintenance'],
  service: ['running', 'stopped', 'degraded', 'maintenance'],
};

const STATUS_OPTION_LABEL = {
  auto: '🧭 Auto (derived)',
  online: '🟢 Online',
  offline: '🔴 Offline',
  degraded: '🟠 Degraded',
  maintenance: '🛠️ Maintenance',
  running: '🟢 Running',
  stopped: '⏹️ Stopped',
};

function encodeRunsOn(item) {
  if (item.hardware_id) return `hw_${item.hardware_id}`;
  if (item.compute_id) return `cu_${item.compute_id}`;
  return '';
}

function isLightTheme(settings) {
  return settings.theme === 'light'
    || (settings.theme === 'auto' && globalThis.matchMedia('(prefers-color-scheme: light)').matches);
}

function getQuickCreateTitle(mode) {
  if (mode === 'service') return 'New Service';
  if (mode === 'compute') return 'New Compute Unit';
  return 'New Storage';
}

function slugifyName(name) {
  return String(name || '')
    .trim()
    .toLowerCase()
    .replaceAll(/[^a-z0-9]+/g, '-')
    .replaceAll(/^-+|-+$/g, '');
}

function makeBulkRow(mode, defaults = {}) {
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

function buildBulkServicePayload(row, initialValues) {
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
    payload.ports = [{
      port: Number.parseInt(row.port, 10),
      protocol: row.protocol || 'tcp',
    }];
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

function buildBulkComputePayload(row, initialValues) {
  return {
    name: row.name.trim(),
    kind: row.kind || 'vm',
    hardware_id: initialValues?.hardware_id || null,
    ip_address: row.ip_address?.trim() || null,
    os: row.os || null,
    icon_slug: row.icon_slug?.trim() || null,
  };
}

function buildBulkStoragePayload(row, initialValues) {
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

function validateBulkRows(mode, rows) {
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

async function runBulkCreate(mode, rows, initialValues) {
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
      failed.push({ rowId: row.id, name: row.name || 'Unnamed', message: err?.message || 'Create failed' });
    }
  }

  return { successCount, failed };
}

function getServiceDefaults(targetNode) {
  if (!targetNode?._refId) return {};
  if (targetNode.originalType === 'compute') return { runs_on: `cu_${targetNode._refId}` };
  if (targetNode.originalType === 'hardware') return { runs_on: `hw_${targetNode._refId}` };
  return {};
}

function getComputeDefaults(targetNode, kindHint) {
  const defaults = {};
  if (kindHint) defaults.kind = kindHint;
  if (targetNode?.originalType === 'hardware' && targetNode._refId) defaults.hardware_id = targetNode._refId;
  return defaults;
}

function getStorageDefaults(targetNode) {
  if (targetNode?.originalType === 'hardware' && targetNode._refId) {
    return { hardware_id: targetNode._refId };
  }
  return {};
}

function getDefaultQuickCreateValues(mode, targetNode, kindHint = null) {
  if (mode === 'service') return getServiceDefaults(targetNode);
  if (mode === 'compute') return getComputeDefaults(targetNode, kindHint);
  if (mode === 'storage') return getStorageDefaults(targetNode);
  return {};
}

function DeleteConflictModal({ modal, onCancel, onForceRemove }) {
  if (!modal?.open) return null;

  return (
    <div className="modal-overlay">
      <dialog open className="modal" aria-labelledby="delete-conflict-title" style={{ width: 460, margin: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
          <h3 id="delete-conflict-title">Delete Conflict</h3>
          <button
            type="button"
            className="btn"
            aria-label="Close delete conflict dialog"
            onClick={onCancel}
            style={{ width: 28, height: 28, padding: 0, borderRadius: 999, display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
          >
            <X size={14} />
          </button>
        </div>
        <p style={{ marginTop: 10, color: 'var(--color-text-muted)', fontSize: 13 }}>
          Could not delete <strong>{modal.nodeLabel}</strong> because related links/dependencies still exist.
        </p>
        {modal.reason && (
          <p style={{ marginTop: 8, color: 'var(--color-danger)', fontSize: 12 }}>
            {modal.reason}
          </p>
        )}
        {modal.blockers.length > 0 && (
          <div style={{ marginTop: 12, maxHeight: 180, overflowY: 'auto', border: '1px solid var(--color-border)', borderRadius: 8 }}>
            {modal.blockers.map((b, i) => (
              <div
                key={`${b.edgeId}-${i}`}
                style={{
                  padding: '8px 10px',
                  borderBottom: i < modal.blockers.length - 1 ? '1px solid var(--color-border)' : 'none',
                  fontSize: 12,
                }}
              >
                <span style={{ color: 'var(--color-text)' }}>{b.otherLabel}</span>
                <span style={{ color: 'var(--color-text-muted)' }}> · {b.relation}</span>
              </div>
            ))}
          </div>
        )}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 16 }}>
          <button
            type="button"
            className="btn"
            disabled={modal.forcing}
            onClick={onCancel}
          >
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-danger"
            disabled={modal.forcing}
            onClick={onForceRemove}
          >
            {modal.forcing ? 'Removing…' : 'Force remove'}
          </button>
        </div>
      </dialog>
    </div>
  );
}

DeleteConflictModal.propTypes = {
  modal: PropTypes.shape({
    open: PropTypes.bool,
    nodeLabel: PropTypes.string,
    reason: PropTypes.string,
    forcing: PropTypes.bool,
    blockers: PropTypes.arrayOf(PropTypes.shape({
      edgeId: PropTypes.string,
      relation: PropTypes.string,
      otherLabel: PropTypes.string,
    })),
  }).isRequired,
  onCancel: PropTypes.func.isRequired,
  onForceRemove: PropTypes.func.isRequired,
};

// ── Layout Algorithms ───────────────────────────────────────────────────────
// Note: Core layout engines are now imported from utils/layouts.js.


// ── Edge Routing Helpers ─────────────────────────────────────────────────────

/**
 * Determine the optimal side for an edge to exit/enter based on the relative
 * positions of the source and target nodes.
 *
 * If the horizontal distance dominates → exit the side that faces the target
 * (right when target is to the right, left when target is to the left).
 * Otherwise use top/bottom for primarily vertical connections.
 */
function computeSide(sourcePos, targetPos) {
  const dx = targetPos.x - sourcePos.x;
  const dy = targetPos.y - sourcePos.y;
  if (Math.abs(dx) > Math.abs(dy)) {
    return { sourceSide: dx > 0 ? 'right' : 'left', targetSide: dx > 0 ? 'left' : 'right' };
  }
  return { sourceSide: dy > 0 ? 'bottom' : 'top', targetSide: dy > 0 ? 'top' : 'bottom' };
}

/**
 * Apply sourceHandle / targetHandle to edges based on relative node positions.
 *
 * @param {Node[]} nodesArr - current nodes with positions
 * @param {Edge[]} edgesArr - current edges
 * @param {Object} overrides - edgeId → { source_side, target_side, control_point }
 * @param {string|null} onlyNodeId - if set, only recompute edges connected to this node
 */
function applyEdgeSides(nodesArr, edgesArr, overrides = {}, onlyNodeId = null) {
  const posMap = Object.fromEntries(nodesArr.map(n => [n.id, n.position]));
  return edgesArr.map(e => {
    const isConnected = e.source === onlyNodeId || e.target === onlyNodeId;
    if (onlyNodeId && !isConnected) return e;

    const override = overrides[e.id];
    const src = posMap[e.source] ?? { x: 0, y: 0 };
    const tgt = posMap[e.target] ?? { x: 0, y: 0 };
    const { sourceSide, targetSide } = override
      ? { sourceSide: override.source_side, targetSide: override.target_side }
      : computeSide(src, tgt);

    return {
      ...e,
      sourceHandle: `s-${sourceSide}`,
      targetHandle: `t-${targetSide}`,
      data: {
        ...e.data,
        controlPoint: override?.control_point ?? e.data?.controlPoint ?? null,
      },
    };
  });
}

/**
 * Parse the stored layout JSON — handles both the new format
 *   { nodes: {...}, edges: {...} }
 * and the legacy format
 *   { "hw-1": {x,y}, ... }  (flat node position map).
 */
function parseLayoutData(raw) {
  const parsed = JSON.parse(raw);
  if (parsed && typeof parsed.nodes === 'object' && !Array.isArray(parsed.nodes)) {
    return { nodes: parsed.nodes || {}, edges: parsed.edges || {}, boundaries: parsed.boundaries || [] };
  }
  return { nodes: parsed || {}, edges: {}, boundaries: [] };
}

function normalizeBoundaryName(name, index) {
  const trimmed = String(name || '').trim();
  return trimmed || `Boundary ${index + 1}`;
}

function boundaryFlowRect(startFlow, endFlow) {
  return {
    minX: Math.min(startFlow.x, endFlow.x),
    maxX: Math.max(startFlow.x, endFlow.x),
    minY: Math.min(startFlow.y, endFlow.y),
    maxY: Math.max(startFlow.y, endFlow.y),
  };
}

function nodeCenterInFlow(node) {
  const width = Number(node?.width || 140);
  const height = Number(node?.height || 140);
  const basePos = node?.positionAbsolute || node?.position || { x: 0, y: 0 };
  const x = Number(basePos.x || 0) + (width / 2);
  const y = Number(basePos.y || 0) + (height / 2);
  return { x, y };
}

function pointInRect(point, rect) {
  return point.x >= rect.minX && point.x <= rect.maxX && point.y >= rect.minY && point.y <= rect.maxY;
}

function cross(o, a, b) {
  return ((a.x - o.x) * (b.y - o.y)) - ((a.y - o.y) * (b.x - o.x));
}

function convexHull(points) {
  if (points.length <= 1) return points;
  const sorted = [...points].sort((a, b) => (a.x - b.x) || (a.y - b.y));

  const lower = [];
  for (const point of sorted) {
    while (lower.length >= 2 && cross(lower.at(-2), lower.at(-1), point) <= 0) lower.pop();
    lower.push(point);
  }

  const upper = [];
  for (let i = sorted.length - 1; i >= 0; i -= 1) {
    const point = sorted[i];
    while (upper.length >= 2 && cross(upper.at(-2), upper.at(-1), point) <= 0) upper.pop();
    upper.push(point);
  }

  lower.pop();
  upper.pop();
  return [...lower, ...upper];
}

function expandPolygon(points, padding = 46) {
  if (!points.length) return points;
  const centroid = points.reduce((acc, point) => ({ x: acc.x + point.x, y: acc.y + point.y }), { x: 0, y: 0 });
  centroid.x /= points.length;
  centroid.y /= points.length;

  return points.map((point) => {
    const dx = point.x - centroid.x;
    const dy = point.y - centroid.y;
    const dist = Math.hypot(dx, dy) || 1;
    return {
      x: Math.round((point.x + ((dx / dist) * padding)) * 10) / 10,
      y: Math.round((point.y + ((dy / dist) * padding)) * 10) / 10,
    };
  });
}

function computeBoundaryPolygon(boundary, nodesArr) {
  const members = nodesArr.filter((node) => boundary.memberIds?.includes(node.id));
  if (members.length < 1) return [];

  const cloud = [];
  members.forEach((node) => {
    const width = Number(node?.width || 140);
    const height = Number(node?.height || 140);
    const basePos = node?.positionAbsolute || node?.position || { x: 0, y: 0 };
    const x = Number(basePos.x || 0);
    const y = Number(basePos.y || 0);
    cloud.push(
      { x: x - 18, y: y - 20 },
      { x: x + width + 18, y: y - 20 },
      { x: x - 18, y: y + height + 20 },
      { x: x + width + 18, y: y + height + 20 },
    );
  });

  const hull = convexHull(cloud);
  return expandPolygon(hull, 28);
}

function boundaryLabelFlowAnchor(points) {
  if (!points.length) return null;
  const sum = points.reduce((acc, p) => ({ x: acc.x + p.x, y: acc.y + p.y }), { x: 0, y: 0 });
  return { x: sum.x / points.length, y: sum.y / points.length };
}

function flowToScreenPoint(point, viewportValue) {
  return {
    x: (point.x * viewportValue.zoom) + viewportValue.x,
    y: (point.y * viewportValue.zoom) + viewportValue.y,
  };
}

function boundaryPath(points, viewportValue) {
  if (!points.length) return '';
  const screenPoints = points.map((point) => flowToScreenPoint(point, viewportValue));
  return screenPoints.map((point, index) => `${index === 0 ? 'M' : 'L'} ${point.x} ${point.y}`).join(' ') + ' Z';
}

function distanceBetweenPositions(a, b) {
  const dx = (a?.x ?? 0) - (b?.x ?? 0);
  const dy = (a?.y ?? 0) - (b?.y ?? 0);
  return Math.hypot(dx, dy);
}

function hasNodeCollision(candidate, nodesArr, movingNodeId, threshold = 150) {
  return nodesArr.some((node) => {
    if (!node || node.id === movingNodeId) return false;
    if (!node.position || typeof node.position.x !== 'number' || typeof node.position.y !== 'number') return false;
    return distanceBetweenPositions(candidate, node.position) < threshold;
  });
}

function resolveNonOverlappingPosition(candidate, nodesArr, movingNodeId) {
  if (!hasNodeCollision(candidate, nodesArr, movingNodeId)) return candidate;

  const radiusStep = 90;
  const angleStep = 20;
  const maxRings = 8;

  for (let ring = 1; ring <= maxRings; ring += 1) {
    const radius = radiusStep * ring;
    for (let angle = 0; angle < 360; angle += angleStep) {
      const rad = (Math.PI / 180) * angle;
      const testPos = {
        x: Math.round((candidate.x + (radius * Math.cos(rad))) * 10) / 10,
        y: Math.round((candidate.y + (radius * Math.sin(rad))) * 10) / 10,
      };
      if (!hasNodeCollision(testPos, nodesArr, movingNodeId)) return testPos;
    }
  }

  return candidate;
}

// ── Main Component ──────────────────────────────────────────────────────────

function MapInternal() {
  const isMobile = useIsMobile();
  const { fitView, project } = useReactFlow();
  const viewport = useViewport();
  const { settings } = useSettings();
  const toast = useToast();
  const navigate = useNavigate();

  const isLight = isLightTheme(settings);
  const bgGridColor = isLight ? '#c8d4e0' : '#1a2035';

  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [layoutEngine, setLayoutEngine] = useState('dagre');
  const [cloudViewEnabled, setCloudViewEnabled] = useState(false);
  const [lastSaved, setLastSaved] = useState(null);
  const dirtyRef = useRef(false);
  const [showLabels, setShowLabels] = useState(!isMobile);

  const [legendOpen, setLegendOpen] = useState(() => {
    const saved = localStorage.getItem('cb-legend-open');
    if (saved !== null) return saved === 'true';
    return !isMobile;
  });

  useEffect(() => {
    localStorage.setItem('cb-legend-open', legendOpen);
  }, [legendOpen]);

  // Edge override state — { edgeId: { source_side, target_side, control_point? } }
  const [edgeOverrides, setEdgeOverrides] = useState({});
  const [boundaries, setBoundaries] = useState([]);
  const [boundaryDrawMode, setBoundaryDrawMode] = useState(false);
  const [boundaryDraft, setBoundaryDraft] = useState(null);
  const [editingBoundaryId, setEditingBoundaryId] = useState(null);
  const [editingBoundaryName, setEditingBoundaryName] = useState('');
  // Edge anchor context menu — { edgeId, x, y } | null
  const [edgeMenu, setEdgeMenu] = useState(null);
  // Pending connection action (new connect or reconnect), resolved by type picker
  const [pendingConnection, setPendingConnection] = useState(null);

  // Stable refs so callbacks can always access the latest values
  const nodesRef = useRef([]);
  const edgeOverridesRef = useRef({});
  const flowContainerRef = useRef(null);
  const lastPointerRef = useRef({ x: 220, y: 120 });
  const boundaryDraftRef = useRef(null);
  const boundaryPointerMoveRef = useRef(null);
  const boundaryPointerUpRef = useRef(null);
  const finishBoundaryDrawRef = useRef(() => {});

  // Keep refs in sync with state
  useEffect(() => { nodesRef.current = nodes; }, [nodes]);
  useEffect(() => { edgeOverridesRef.current = edgeOverrides; }, [edgeOverrides]);
  useEffect(() => { boundaryDraftRef.current = boundaryDraft; }, [boundaryDraft]);

  // Stable ref that SmartEdge reads via MapEdgeCallbacksContext
  const edgeCallbacksRef = useRef(null);

  // Pending discoveries badge
  const [pendingDiscoveries, setPendingDiscoveries] = useState(0);
  useEffect(() => {
    getPendingResults({ limit: 1 }).then((r) => setPendingDiscoveries(r.data?.total ?? 0)).catch(() => {});
    const onAdded = () => setPendingDiscoveries((c) => c + 1);
    discoveryEmitter.on('result:added', onAdded);
    return () => discoveryEmitter.off('result:added', onAdded);
  }, []);

  // Filters
  const [envFilter, setEnvFilter] = useState('');
  const [environmentsList, setEnvironmentsList] = useState([]);
  const [tagFilter, setTagFilter] = useState('');
  const [includeTypes, setIncludeTypes] = useState({
    cluster: true, hardware: true, compute: true, service: true,
    storage: true, network: true, misc: true, external: true,
  });
  // Sub-role filter for hardware nodes (null = show all)
  const [hwRoleFilter, setHwRoleFilter] = useState(null);

  // Tooltip state
  const [tooltip, setTooltip] = useState(null);

  // Context menu state (node)
  const [contextMenu, setContextMenu] = useState(null); // { x, y, node } | null
  const [createNodeModal, setCreateNodeModal] = useState({ isOpen: false, position: null });
  const [iconPickerOpen, setIconPickerOpen] = useState(false);
  const [iconPickerNode, setIconPickerNode] = useState(null);
  const [quickActionModal, setQuickActionModal] = useState(null);
  const [quickActionValue, setQuickActionValue] = useState('');
  const [quickActionSaving, setQuickActionSaving] = useState(false);
  const [roleModal, setRoleModal] = useState({
    open: false,
    nodeRefId: null,
    nodeLabel: '',
    currentRole: '',
    isEdit: false,
  });
  const [quickCreateModal, setQuickCreateModal] = useState({
    open: false,
    mode: null,
    title: '',
    sourceLabel: '',
    initialValues: {},
  });
  const [quickCreateRows, setQuickCreateRows] = useState([]);
  const [quickCreateRowErrors, setQuickCreateRowErrors] = useState({});
  const [quickCreateSaving, setQuickCreateSaving] = useState(false);
  const [confirmState, setConfirmState] = useState({ open: false, message: '', onConfirm: null });
  const [deleteConflictModal, setDeleteConflictModal] = useState({
    open: false,
    nodeId: null,
    nodeRefId: null,
    nodeType: null,
    nodeLabel: '',
    blockers: [],
    reason: '',
    forcing: false,
  });

  const clearBoundaryPointerListeners = useCallback(() => {
    if (boundaryPointerMoveRef.current) {
      window.removeEventListener('pointermove', boundaryPointerMoveRef.current);
      boundaryPointerMoveRef.current = null;
    }
    if (boundaryPointerUpRef.current) {
      window.removeEventListener('pointerup', boundaryPointerUpRef.current);
      boundaryPointerUpRef.current = null;
    }
  }, []);

  // Esc key to dismiss context menus
  useEffect(() => {
    function handleKeyDown(e) {
      if (e.key === 'Escape') {
        clearBoundaryPointerListeners();
        setContextMenu(null);
        setEdgeMenu(null);
        setPendingConnection(null);
        setBoundaryDrawMode(false);
        setBoundaryDraft(null);
        setEditingBoundaryId(null);
        setEditingBoundaryName('');
        setCreateNodeModal({ isOpen: false, position: null });
        setIconPickerOpen(false);
        setIconPickerNode(null);
        setQuickActionModal(null);
        setQuickActionValue('');
        setQuickCreateModal({ open: false, mode: null, title: '', sourceLabel: '', initialValues: {} });
        setQuickCreateRows([]);
        setQuickCreateRowErrors({});
        setDeleteConflictModal((m) => ({ ...m, open: false, forcing: false }));
      }
    }
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [clearBoundaryPointerListeners]);

  useEffect(() => {
    return () => {
      clearBoundaryPointerListeners();
    };
  }, [clearBoundaryPointerListeners]);

  // Selected node side panel
  const [selectedNode, setSelectedNode] = useState(null);

  // Debounce tag filter
  const tagDebounceRef = useRef(null);
  const [debouncedTag, setDebouncedTag] = useState('');

  // Fetch environments list for filter dropdown
  useEffect(() => {
    environmentsApi.list().then((r) => setEnvironmentsList(r.data)).catch(() => {});
  }, []);

  // Settings initialization (run once after settings load)
  const settingsApplied = useRef(false);
  useEffect(() => {
    if (settings && !settingsApplied.current) {
      settingsApplied.current = true;
      if (settings.default_environment) {
        // Match default_environment string to an environment id
        // (will be reconciled after environmentsList loads)
        setEnvFilter(settings.default_environment);
      }
      if (settings.map_default_filters && typeof settings.map_default_filters === 'object') {
        const f = settings.map_default_filters;
        if (f.include && typeof f.include === 'object') {
          setIncludeTypes(prev => ({ ...prev, ...f.include }));
        }
      }
    }
  }, [settings]);

  useEffect(() => {
    clearTimeout(tagDebounceRef.current);
    tagDebounceRef.current = setTimeout(() => setDebouncedTag(tagFilter), 300);
    return () => clearTimeout(tagDebounceRef.current);
  }, [tagFilter]);

  // Re-apply tag filter client-side (preserves positions via hidden property)
  useEffect(() => {
    const trimmedTag = debouncedTag.trim().toLowerCase();
    setNodes(prev => prev.map(n => ({ ...n, hidden: isHiddenByTag(n, trimmedTag) })));
    setEdges(prev => prev.map(e => {
      if (!trimmedTag) return { ...e, hidden: false };
      return e; // edge visibility handled by ReactFlow when both nodes are hidden
    }));
  }, [debouncedTag, setNodes, setEdges]);

  // Hardware sub-role filter — hide/show hardware nodes by role
  useEffect(() => {
    setNodes(prev => prev.map(n => {
      if (n.originalType !== 'hardware') return n;
      return { ...n, hidden: hwRoleFilter ? n._hwRole !== hwRoleFilter : false };
    }));
  }, [hwRoleFilter, setNodes]);

  // Telemetry polling — refresh every 60s for hardware nodes that have active telemetry
  useEffect(() => {
    const interval = setInterval(() => {
      const liveHwNodes = nodesRef.current.filter(
        n => n.originalType === 'hardware' && n.data.telemetry_status && n.data.telemetry_status !== 'unknown'
      );
      liveHwNodes.forEach(async (n) => {
        try {
          const res = await telemetryApi.get(n._refId);
          setNodes(applyTelemetryUpdate(nodesRef.current, n.id, res));
        } catch { /* silent — connection may be unavailable */ }
      });
    }, 60_000);
    return () => clearInterval(interval);
  }, [setNodes]);

  const getIncludeCSV = (types) => {
    const MAP = { hardware: 'hardware', compute: 'compute', service: 'services', storage: 'storage', network: 'networks', misc: 'misc', external: 'external' };
    return Object.entries(types).filter(([, v]) => v).map(([k]) => MAP[k]).filter(Boolean).join(',') || 'hardware';
  };

  const getLayoutName = useCallback(() => {
    return envFilter ? `default::envid:${envFilter}` : 'default';
  }, [envFilter]);

  const clampPickerPosition = useCallback((x, y) => {
    const rect = flowContainerRef.current?.getBoundingClientRect();
    if (!rect) return { x: 24, y: 24 };
    const width = 240;
    const height = 180;
    const clampedX = Math.max(8, Math.min(x, rect.width - width - 8));
    const clampedY = Math.max(8, Math.min(y, rect.height - height - 8));
    return { x: clampedX, y: clampedY };
  }, []);

  const getTopologyParams = useCallback(() => ({
    environment_id: envFilter || undefined,
    include: getIncludeCSV(includeTypes),
  }), [envFilter, includeTypes]);

  const getNewestEdgeId = useCallback((edgesArr, predicate) => {
    const candidates = edgesArr.filter(predicate);
    candidates.sort((a, b) => {
      const aNum = Number((a.id.match(/(\\d+)(?!.*\\d)/) || [])[1] || 0);
      const bNum = Number((b.id.match(/(\\d+)(?!.*\\d)/) || [])[1] || 0);
      return bNum - aNum;
    });
    return candidates[0]?.id || null;
  }, []);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const includeCSV = getIncludeCSV(includeTypes);
      const res = await graphApi.topology({
        environment_id: envFilter || undefined,
        include: includeCSV,
      });

      const rawN = res.data.nodes.map(n => {
        const nodeShell = {
          id: n.id,
          type: 'iconNode',
          className: n.role === 'switch' ? 'node-switch' : '',
          data: {},
          position: { x: 0, y: 0 },
          style: { ...BASE_NODE_STYLE },
          hidden: n.type === 'cluster' && !includeTypes.cluster,
          originalType: n.type,
          _tags: n.tags || [],
          _refId: n.ref_id,
          _computeId: n.compute_id || null,
          _hwId: n.hardware_id || null,
          _hwRole: n.type === 'hardware' ? (n.role || null) : null,
        };
        // Compute rank early so it's available in node.data for tooltips/debug
        const rank = getNodeRank(nodeShell);
        nodeShell.data = {
          label: n.label,
          role: n.role || null,
          iconSrc: resolveNodeIcon(n.type, n.icon_slug, n.vendor, n.kind, n.role),
          icon_slug: n.icon_slug ?? null,
          glowColor: NODE_STYLES[n.type]?.glowColor,
          rank,
          ip_address: n.ip_address || null,
          ports: Array.isArray(n.ports) ? n.ports : [],
          cidr: n.cidr || null,
          storage_summary: n.storage_summary || null,
          storage_allocated: n.storage_allocated || null,
          capacity_gb: n.capacity_gb || null,
          used_gb: n.used_gb || null,
          ...(n.type === 'cluster' ? { member_count: n.member_count, environment: n.environment } : {}),
          status: n.status || null,
          status_override: n.status_override || null,
          telemetry_status: n.telemetry_status || 'unknown',
          telemetry_data: n.telemetry_data || null,
          telemetry_last_polled: n.telemetry_last_polled || null,
          u_height: n.u_height ?? 1,
          rack_unit: n.rack_unit ?? null,
          ip_conflict: n.ip_conflict ?? false,
          download_speed_mbps: n.download_speed_mbps ?? null,
          upload_speed_mbps: n.upload_speed_mbps ?? null,
        };
        return nodeShell;
      });

      const rawE = res.data.edges.map(e => {
        const color = EDGE_COLORS[e.relation] || '#6c7086';
        const relation = e.data?.relation || e.relation;
        return {
          id: e.id,
          source: e.source,
          target: e.target,
          type: 'smart',
          label: showLabels ? relation : '',
          animated: e.relation === 'depends_on' || e.relation === 'runs',
          style: { stroke: color, strokeWidth: 1.5, opacity: 0.75 },
          _relation: e.relation,
          data: {
            label: relation,
            relation,
            controlPoint: null,
            connection_type: normalizeConnectionType(e.data?.connection_type),
            bandwidth: e.data?.bandwidth || null,
          },
        };
      });

      const clusterMembers = new Set();
      rawE.forEach((e) => {
        if (e._relation === 'cluster_member' || e.data?.relation === 'cluster_member') {
          clusterMembers.add(e.source);
          clusterMembers.add(e.target);
        }
      });
      const rawNodesWithClusterHints = rawN.map((node) => ({
        ...node,
        data: {
          ...node.data,
          isClusterMember: clusterMembers.has(node.id),
        },
      }));

      // Try to load saved layout (environment-scoped with default fallback)
      let savedNodePositions = null;
      let savedEdgeOverrides = {};
      let savedBoundaries = [];
      try {
        const scopedLayoutName = getLayoutName();
        const layoutNames = scopedLayoutName === 'default'
          ? ['default']
          : [scopedLayoutName, 'default'];

        for (const layoutName of layoutNames) {
          const layoutRes = await graphApi.getLayout(layoutName);
          if (!layoutRes.data.layout_data) continue;
          const parsed = parseLayoutData(layoutRes.data.layout_data);
          savedNodePositions = parsed.nodes;
          savedEdgeOverrides = parsed.edges || {};
          savedBoundaries = Array.isArray(parsed.boundaries) ? parsed.boundaries : [];
          setLastSaved(layoutRes.data.updated_at);
          break;
        }
      } catch { /* no saved layout */ }

      setBoundaries(
        savedBoundaries
          .filter((boundary) => Array.isArray(boundary?.memberIds) && boundary.memberIds.length >= 1)
          .map((boundary, index) => ({
            id: boundary.id || `boundary-${Date.now()}-${index}`,
            name: normalizeBoundaryName(boundary.name, index),
            memberIds: boundary.memberIds,
          })),
      );

      if (savedNodePositions) {
        const mergedNodes = rawNodesWithClusterHints.map(n => {
          if (savedNodePositions[n.id]) return { ...n, position: savedNodePositions[n.id] };
          // Mark for auto placement
          return { ...n, position: { x: 0, y: 0 }, _needsAutoPlace: true };
        });
        setEdgeOverrides(savedEdgeOverrides);
        edgeOverridesRef.current = savedEdgeOverrides;
        
        let initialNodes = mergedNodes;
        if (cloudViewEnabled) {
          initialNodes = groupNodesIntoCloud(initialNodes);
        }

        setNodes(initialNodes);
        setEdges(applyEdgeSides(mergedNodes, rawE, savedEdgeOverrides));
        setLayoutEngine('manual');
      } else {
        // Node count heuristic: use Tree for very large graphs instead of DAG
        const layout = getDagreLayout(rawNodesWithClusterHints, rawE, 'TB');
        let initialNodes = layout.nodes;
        if (cloudViewEnabled) {
          initialNodes = groupNodesIntoCloud(initialNodes);
        }

        setNodes(initialNodes);
        setEdges(applyEdgeSides(initialNodes, layout.edges, {}));
        setLayoutEngine('dagre');
      }

      setTimeout(() => {
        fitView({ padding: 0.2 });
        if (isMobile) {
          // Defer edge labels for smoother initial paint on mobile
          setTimeout(() => setShowLabels(true), 300);
        }
      }, 50);
    } catch (err) {
      setError(err.message || 'Failed to load topology');
    } finally {
      setLoading(false);
    }
  }, [envFilter, includeTypes, fitView, getLayoutName, isMobile, showLabels, cloudViewEnabled]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // Handle Cloud View Toggle independent of fetch
  useEffect(() => {
    if (cloudViewEnabled) {
      setNodes((nds) => groupNodesIntoCloud(nds));
      setTimeout(() => fitView({ duration: 800, padding: 0.2 }), 100);
    } else {
      setNodes((nds) => restoreFromCloudView(nds));
      setTimeout(() => fitView({ duration: 800, padding: 0.2 }), 100);
    }
  }, [cloudViewEnabled, setNodes, fitView]);

  const applyLayout = useCallback((engine) => {
    setLoading(true);

    if (engine === 'manual') {
      setLayoutEngine('manual');
      setLoading(false);
      return;
    }

    setTimeout(() => {
      let layout;
      
      // We must flatten nodes before re-layout if cloud view is on, 
      // but it's simpler to layout the base nodes, then re-apply cloud.
      
      const baseNodes = cloudViewEnabled ? restoreFromCloudView(nodes) : [...nodes];

      if (engine === 'dagre') layout = getDagreLayout(baseNodes, edges, 'TB');
      else if (engine === 'force') layout = getForceLayout(baseNodes, edges);
      else if (engine === 'tree') layout = getTreeLayout(baseNodes, edges);

      if (layout) {
        let finalNodes = layout.nodes;
        if (cloudViewEnabled) {
          finalNodes = groupNodesIntoCloud(finalNodes);
        }
        setNodes(finalNodes);
        setEdges(applyEdgeSides(finalNodes, layout.edges, edgeOverridesRef.current));
        setTimeout(() => fitView({ duration: 800, padding: 0.2 }), 10);
      }
      setLayoutEngine(engine);
      dirtyRef.current = true;
      setLoading(false);
    }, 50);
  }, [nodes, edges, setNodes, setEdges, fitView, cloudViewEnabled]);

  const updateNodePos = useCallback((id, pos) => {
    setNodes((nds) => {
      const safePos = resolveNonOverlappingPosition(pos, nds, id);
      return nds.map((n) => (n.id === id ? { ...n, position: safePos, _needsAutoPlace: false } : n));
    });
  }, [setNodes]);

  const autoPlaceNew = useCallback(async (newNodeId) => {
    try {
      const res = await graphApi.placeNode(newNodeId, envFilter || 'default');
      updateNodePos(newNodeId, { x: res.data.x, y: res.data.y });
      toast.success('Node auto-placed safely', { toastId: `placed-${newNodeId}`, autoClose: 2000 });
      dirtyRef.current = true;
    } catch (e) {
      console.error('Auto-place failed', e);
    }
  }, [envFilter, updateNodePos]);

  useEffect(() => {
    // Look for nodes marked with _needsAutoPlace
    const nodesToPlace = nodes.filter(n => n._needsAutoPlace);
    if (nodesToPlace.length > 0) {
      // Process one at a time to prevent overlapping auto-placements
      autoPlaceNew(nodesToPlace[0].id);
    }
  }, [nodes, autoPlaceNew]);

  const saveLayout = async () => {
    const nodePositions = {};
    nodes.forEach(n => { nodePositions[n.id] = n.position; });
    const payload = {
      nodes: nodePositions,
      edges: edgeOverrides,
      boundaries: boundaries.map((boundary, index) => ({
        id: boundary.id,
        name: normalizeBoundaryName(boundary.name, index),
        memberIds: boundary.memberIds,
      })),
    };
    try {
      await graphApi.saveLayout(getLayoutName(), JSON.stringify(payload));
      setLastSaved(new Date().toISOString());
      dirtyRef.current = false;
    } catch (err) {
      setError('Failed to save layout: ' + err.message);
    }
  };

  // ── Node interactions ──────────────────────────────────────────────────────

  const handleNodeMouseEnter = useCallback((event, node) => {
    setTooltip({ x: event.clientX + 14, y: event.clientY - 10, node });
  }, []);

  const handleNodeMouseLeave = useCallback(() => {
    setTooltip(null);
  }, []);

  const handlePaneContextMenu = useCallback((event) => {
    event.preventDefault();
    setContextMenu(null);
    setCreateNodeModal({
      isOpen: true,
      position: project({
        x: event.clientX,
        y: event.clientY - 50
      })
    });
  }, [project]);

  const handleCreateNode = useCallback(async (nodeData) => {
    try {
      const payload = {
        name: nodeData.label,
        hostname: nodeData.label,
        ip_address: nodeData.subLabel || null,
        type: 'hardware',
        role: nodeData.iconType,
        vendor_icon_slug: nodeData.icon_slug || null,
        environment_id: envFilter || undefined
      };
      const res = await hardwareApi.create(payload);
      
      if (res.data?.id) {
        updateNodePos(res.data.id, nodeData.position);
      }
      
      toast.success('Node created');
      setCreateNodeModal({ isOpen: false, position: null });
      fetchData(); 
    } catch (err) {
      toast.error('Failed to create node: ' + err.message);
    }
  }, [envFilter, fetchData, updateNodePos, toast]);

  const handleUpdateStatusAction = useCallback((nodeId) => {
    const targetNode = nodesRef.current.find((n) => n.id === nodeId);
    if (!targetNode) {
      toast.error('Could not resolve node for status update.');
      return;
    }

    const targetType = targetNode.originalType;
    const updater = ENTITY_API_UPDATE_STATUS[targetType];
    const allowed = STATUS_OPTIONS_BY_TYPE[targetType] || [];
    if (!updater || allowed.length === 0 || !targetNode._refId) {
      toast.error('Status updates are not supported for this node type.');
      return;
    }

    const currentRaw = targetNode.data?.status_override || targetNode.data?.status || '';
    const currentValue = currentRaw ? String(currentRaw).toLowerCase() : 'auto';
    setQuickActionModal({
      mode: 'status',
      nodeType: targetType,
      refId: targetNode._refId,
      label: targetNode.data?.label || 'node',
      allowed,
    });
    setQuickActionValue(currentValue);
  }, [toast]);

  const handleAliasAction = useCallback((nodeId) => {
    const targetNode = nodesRef.current.find((n) => n.id === nodeId);
    if (!targetNode) {
      toast.error('Could not resolve node for alias update.');
      return;
    }

    const updater = ENTITY_API_UPDATE_ALIAS[targetNode.originalType];
    if (!updater || !targetNode._refId) {
      toast.error('Alias updates are not supported for this node type.');
      return;
    }

    setQuickActionModal({
      mode: 'alias',
      nodeType: targetNode.originalType,
      refId: targetNode._refId,
      label: targetNode.data?.label || 'node',
    });
    setQuickActionValue(targetNode.data?.label || '');
  }, [toast]);

  const submitAliasQuickAction = useCallback(async (modalData, value) => {
    const updater = ENTITY_API_UPDATE_ALIAS[modalData.nodeType];
    const nextName = value.trim();
    if (!updater) {
      toast.error('Alias updates are not supported for this node type.');
      return false;
    }
    if (!nextName) {
      toast.error('Alias cannot be empty.');
      return false;
    }
    await updater(modalData.refId, nextName);
    toast.success('Alias updated');
    return true;
  }, [toast]);

  const submitStatusQuickAction = useCallback(async (modalData, value) => {
    const updater = ENTITY_API_UPDATE_STATUS[modalData.nodeType];
    const allowed = modalData.allowed || [];
    const normalized = value.trim().toLowerCase();
    if (!updater) {
      toast.error('Status updates are not supported for this node type.');
      return false;
    }
    if (!allowed.includes(normalized)) {
      toast.error(`Invalid status. Allowed values: ${allowed.join(', ')}`);
      return false;
    }
    await updater(modalData.refId, normalized === 'auto' ? '' : normalized);
    toast.success(normalized === 'auto' ? 'Status reset to auto' : `Status updated to ${normalized}`);
    return true;
  }, [toast]);

  const handleSubmitQuickAction = useCallback(async () => {
    if (!quickActionModal) return;
    setQuickActionSaving(true);
    try {
      const ok = quickActionModal.mode === 'alias'
        ? await submitAliasQuickAction(quickActionModal, quickActionValue)
        : await submitStatusQuickAction(quickActionModal, quickActionValue);
      if (!ok) return;

      setQuickActionModal(null);
      setQuickActionValue('');
      fetchData();
    } catch (err) {
      toast.error(err?.message || 'Action failed');
    } finally {
      setQuickActionSaving(false);
    }
  }, [fetchData, quickActionModal, quickActionValue, submitAliasQuickAction, submitStatusQuickAction, toast]);

  const handleRoleAction = useCallback((nodeId) => {
    const targetNode = nodesRef.current.find((n) => n.id === nodeId);
    if (!targetNode) {
      toast.error('Could not resolve node for role update.');
      return;
    }

    if (targetNode.originalType !== 'hardware' || !targetNode._refId) {
      toast.error('Role designation is supported for hardware nodes only.');
      return;
    }

    const currentRole = targetNode._hwRole || '';
    setRoleModal({
      open: true,
      nodeRefId: targetNode._refId,
      nodeLabel: targetNode.data?.label || 'node',
      currentRole,
      isEdit: Boolean(currentRole),
    });
  }, [toast]);

  const handleSubmitRoleModal = useCallback(async (values) => {
    if (!roleModal.nodeRefId) return;

    try {
      await hardwareApi.update(roleModal.nodeRefId, { role: values.role });
      toast.success(roleModal.isEdit ? 'Role updated.' : 'Role designated.');
      setRoleModal({ open: false, nodeRefId: null, nodeLabel: '', currentRole: '', isEdit: false });
      fetchData();
    } catch (err) {
      toast.error(err?.message ?? 'Failed to update role.');
    }
  }, [fetchData, roleModal.isEdit, roleModal.nodeRefId, toast]);

  const openQuickCreateModal = useCallback((mode, nodeId, kindHint = null) => {
    const targetNode = nodesRef.current.find((n) => n.id === nodeId) || null;
    const initialValues = getDefaultQuickCreateValues(mode, targetNode, kindHint);
    setQuickCreateModal({
      open: true,
      mode,
      title: getQuickCreateTitle(mode),
      sourceLabel: targetNode?.data?.label || 'selected node',
      initialValues,
    });
    setQuickCreateRows([makeBulkRow(mode, initialValues)]);
    setQuickCreateRowErrors({});
  }, []);

  const updateQuickCreateRow = useCallback((rowId, key, value) => {
    setQuickCreateRows((rows) => rows.map((row) => (
      row.id === rowId ? { ...row, [key]: value } : row
    )));
    setQuickCreateRowErrors((prev) => {
      if (!prev[rowId]) return prev;
      return { ...prev, [rowId]: '' };
    });
  }, []);

  const addQuickCreateRow = useCallback(() => {
    setQuickCreateRows((rows) => [...rows, makeBulkRow(quickCreateModal.mode, quickCreateModal.initialValues)]);
  }, [quickCreateModal.initialValues, quickCreateModal.mode]);

  const removeQuickCreateRow = useCallback((rowId) => {
    setQuickCreateRows((rows) => rows.filter((row) => row.id !== rowId));
    setQuickCreateRowErrors((prev) => {
      if (!prev[rowId]) return prev;
      const next = { ...prev };
      delete next[rowId];
      return next;
    });
  }, []);

  const handleBulkQuickCreateSubmit = useCallback(async (event) => {
    event.preventDefault();
    const rows = quickCreateRows.filter((row) => Object.values(row).some((v) => String(v ?? '').trim() !== ''));
    if (rows.length === 0) {
      toast.error('Add at least one entry.');
      return;
    }

    const rowValidation = validateBulkRows(quickCreateModal.mode, rows);
    if (Object.keys(rowValidation).length > 0) {
      setQuickCreateRowErrors(rowValidation);
      return;
    }

    setQuickCreateSaving(true);
    const { successCount, failed } = await runBulkCreate(quickCreateModal.mode, rows, quickCreateModal.initialValues);

    if (failed.length > 0) {
      const failedErrors = Object.fromEntries(failed.map((f) => [f.rowId, f.message]));
      setQuickCreateRowErrors(failedErrors);
      if (successCount > 0) {
        toast.info(`Created ${successCount}, failed ${failed.length}.`);
        await fetchData();
      } else {
        toast.error('No entries were created.');
      }
      setQuickCreateSaving(false);
      return;
    }

    await fetchData();
    toast.success(`Created ${successCount} ${quickCreateModal.mode}${successCount === 1 ? '' : 's'}.`);
    setQuickCreateModal({ open: false, mode: null, title: '', sourceLabel: '', initialValues: {} });
    setQuickCreateRows([]);
    setQuickCreateRowErrors({});
    setQuickCreateSaving(false);
  }, [fetchData, quickCreateModal.initialValues, quickCreateModal.mode, quickCreateRows, toast]);

  const handleQuickCreateAction = useCallback((action, nodeId) => {
    if (action === 'add_service') {
      openQuickCreateModal('service', nodeId);
      return true;
    }
    if (action === 'add_container') {
      openQuickCreateModal('compute', nodeId, 'container');
      return true;
    }
    if (action === 'add_vm') {
      openQuickCreateModal('compute', nodeId, 'vm');
      return true;
    }
    if (action === 'add_storage') {
      openQuickCreateModal('storage', nodeId);
      return true;
    }
    if (action === 'add_cluster') {
      navigate('/hardware');
      toast.info('Opened Hardware. Create or edit a cluster to add members.');
      return true;
    }
    return false;
  }, [navigate, openQuickCreateModal, toast]);

  const getDeleteBlockers = useCallback((nodeId) => {
    const currentNodes = nodesRef.current;
    const connected = edges.filter((edge) => edge.source === nodeId || edge.target === nodeId);
    return connected.map((edge) => {
      const otherNodeId = edge.source === nodeId ? edge.target : edge.source;
      const otherNode = currentNodes.find((n) => n.id === otherNodeId);
      return {
        edgeId: edge.id,
        relation: edge._relation || edge.data?.relation || edge.label || 'linked',
        otherLabel: otherNode?.data?.label || otherNodeId,
      };
    });
  }, [edges]);

  const forceRemoveDeleteConflicts = useCallback(async () => {
    if (!deleteConflictModal.nodeId || !deleteConflictModal.nodeRefId || !deleteConflictModal.nodeType) return;
    const deleter = ENTITY_API_DELETE[deleteConflictModal.nodeType];
    if (!deleter) {
      toast.error('Delete is not supported for this node type.');
      return;
    }

    setDeleteConflictModal((m) => ({ ...m, forcing: true }));
    try {
      const connectedEdges = edges.filter(
        (edge) => edge.source === deleteConflictModal.nodeId || edge.target === deleteConflictModal.nodeId,
      );

      for (const edge of connectedEdges) {
        const edgeForUnlink = {
          id: edge.id,
          source: edge.source,
          target: edge.target,
          _relation: edge._relation,
          data: edge.data,
          label: edge.label,
        };
        await unlinkByEdge(edgeForUnlink);
      }

      await deleter(deleteConflictModal.nodeRefId);
      if (selectedNode?.id === deleteConflictModal.nodeId) setSelectedNode(null);
      setDeleteConflictModal((m) => ({ ...m, open: false, forcing: false }));
      toast.success('Node deleted after removing conflicts.');
      fetchData();
    } catch (err) {
      setDeleteConflictModal((m) => ({ ...m, forcing: false }));
      toast.error(err?.message || 'Force remove failed.');
    }
  }, [deleteConflictModal.nodeId, deleteConflictModal.nodeRefId, deleteConflictModal.nodeType, edges, fetchData, selectedNode?.id, toast]);

  const handleDeleteNodeAction = useCallback((nodeId) => {
    const targetNode = nodesRef.current.find((n) => n.id === nodeId);
    if (!targetNode) {
      toast.error('Could not resolve node for deletion.');
      return;
    }

    const deleter = ENTITY_API_DELETE[targetNode.originalType];
    if (!deleter || !targetNode._refId) {
      toast.error('Delete is not supported for this node type.');
      return;
    }

    const label = targetNode.data?.label || targetNode.id;
    setConfirmState({
      open: true,
      message: `Delete node "${label}"? This uses the same delete behavior as the entity page.`,
      onConfirm: async () => {
        setConfirmState((s) => ({ ...s, open: false }));
        try {
          await deleter(targetNode._refId);
          if (selectedNode?.id === targetNode.id) setSelectedNode(null);
          toast.success('Node deleted.');
          fetchData();
        } catch (err) {
          const reason = err?.message || 'Failed to delete node.';
          const blockers = getDeleteBlockers(targetNode.id);
          setDeleteConflictModal({
            open: true,
            nodeId: targetNode.id,
            nodeRefId: targetNode._refId,
            nodeType: targetNode.originalType,
            nodeLabel: label,
            blockers,
            reason,
            forcing: false,
          });
        }
      },
    });
  }, [fetchData, getDeleteBlockers, selectedNode?.id, toast]);

  const handleContextAction = useCallback(async (action, data) => {
    const { nodeId, targetId } = data;
    try {
      if (action.startsWith('link_to_')) {
        await createLinkByNodeIds(nodeId, targetId, true);
        toast.success('Nodes linked successfully');
        fetchData();
      } else if (action === 'edit_icon') {
        const targetNode = nodesRef.current.find((n) => n.id === nodeId);
        if (!targetNode) {
          toast.error('Could not resolve node for icon editing.');
          return;
        }
        setIconPickerNode(targetNode);
        setIconPickerOpen(true);
      } else if (action === 'alias') {
        handleAliasAction(nodeId);
      } else if (action === 'edit_role') {
        handleRoleAction(nodeId);
      } else if (action === 'update_status') {
        handleUpdateStatusAction(nodeId);
      } else if (action === 'delete_node') {
        handleDeleteNodeAction(nodeId);
      } else if (handleQuickCreateAction(action, nodeId)) {
        return;
      } else {
         toast.info(`Action ${action} triggered but specific handler not implemented yet`);
      }
    } catch (err) {
      toast.error(`Action failed: ${err.message}`);
    }
  }, [fetchData, handleAliasAction, handleDeleteNodeAction, handleQuickCreateAction, handleRoleAction, handleUpdateStatusAction, toast]);

  const handleIconPick = useCallback(async (slug) => {
    if (!iconPickerNode) return;
    const updater = ENTITY_API_UPDATE_ICON[iconPickerNode.originalType];
    if (!updater || !iconPickerNode._refId) {
      toast.error('Icon editing is not supported for this node type.');
      return;
    }

    try {
      await updater(iconPickerNode._refId, slug);
      toast.success('Icon updated');
      setIconPickerOpen(false);
      setIconPickerNode(null);
      fetchData();
    } catch (err) {
      toast.error(err?.message || 'Failed to update icon');
    }
  }, [fetchData, iconPickerNode, toast]);

  const handleNodeContextMenu = useCallback((event, node) => {
    event.preventDefault();
    setTooltip(null);
    setContextMenu({ x: event.clientX, y: event.clientY, node });
  }, []);

  const handleNodeClick = useCallback((event, node) => {
    setTooltip(null);
    setSelectedNode(node);
  }, []);

  const handlePaneClick = useCallback(() => {
    setContextMenu(null);
    if (selectedNode) setSelectedNode(null);
  }, [selectedNode]);

  useEffect(() => {
    if (!selectedNode) return;
    const refreshed = nodes.find((node) => node.id === selectedNode.id);
    if (!refreshed) return;
    setSelectedNode(refreshed);
  }, [nodes, selectedNode]);

  const handleUplinkChange = useCallback((nodeId, uplinkMbps) => {
    const value = Number(uplinkMbps);
    if (!Number.isFinite(value) || value <= 0) return;

    const updatedNodes = nodesRef.current.map((node) => {
      if (node.id !== nodeId) return node;
      return {
        ...node,
        data: {
          ...node.data,
          uplinkSpeed: value,
          upload_speed_mbps: value,
        },
      };
    });

    nodesRef.current = updatedNodes;
    setNodes(updatedNodes);
    setEdges((prev) => recalculateAllEdges(updatedNodes, prev));

    if (selectedNode?.id === nodeId) {
      const refreshed = updatedNodes.find((node) => node.id === nodeId);
      if (refreshed) setSelectedNode(refreshed);
    }
  }, [selectedNode?.id, setEdges, setNodes]);

  const selectedNodeAnchor = useMemo(() => {
    if (!selectedNode) return null;

    const flowPos = selectedNode.positionAbsolute || selectedNode.position || { x: 0, y: 0 };
    const nodeWidth = selectedNode.width || 140;
    const nodeHeight = selectedNode.height || 140;

    return {
      x: viewport.x + ((flowPos.x + nodeWidth) * viewport.zoom) + 14,
      y: viewport.y + ((flowPos.y + (nodeHeight / 2)) * viewport.zoom),
    };
  }, [selectedNode, viewport.x, viewport.y, viewport.zoom]);

  const selectedNodeRelationships = useMemo(() => {
    if (!selectedNode) return [];

    return buildRelatedNodes(selectedNode.id, nodes, edges).map((item) => ({
      direction: item.direction,
      relation: item.relation || 'linked_to',
      nodeId: item.node.id,
      nodeLabel: item.node.data?.alias || item.node.data?.label || item.node.id,
      nodeType: item.node.originalType || item.node.data?.type || 'node',
      nodeAddress: item.node.data?.ip_address || item.node.data?.cidr || null,
    }));
  }, [edges, nodes, selectedNode]);

  const selectedNodeSysinfo = useMemo(() => buildNodeSysinfoRows(selectedNode), [selectedNode]);
  const selectedNodeStatus = useMemo(() => buildNodeStatusDetails(selectedNode), [selectedNode]);

  const boundaryRenderData = useMemo(() => (
    boundaries
      .map((boundary, index) => {
        const polygon = computeBoundaryPolygon(boundary, nodes);
        if (polygon.length < 3) return null;
        const anchorFlow = boundaryLabelFlowAnchor(polygon);
        if (!anchorFlow) return null;
        const anchorScreen = flowToScreenPoint(anchorFlow, viewport);
        return {
          id: boundary.id,
          name: normalizeBoundaryName(boundary.name, index),
          path: boundaryPath(polygon, viewport),
          anchorScreen,
        };
      })
      .filter(Boolean)
  ), [boundaries, nodes, viewport]);

  const handlePanePointerDown = useCallback((event) => {
    if (!boundaryDrawMode || event.button !== 0) return;
    event.preventDefault();
    const initialDraft = {
      startClient: { x: event.clientX, y: event.clientY },
      endClient: { x: event.clientX, y: event.clientY },
    };
    clearBoundaryPointerListeners();
    setBoundaryDraft(initialDraft);
    boundaryDraftRef.current = initialDraft;

    const onPointerMove = (moveEvent) => {
      setBoundaryDraft((draft) => {
        if (!draft) return draft;
        const updated = {
          ...draft,
          endClient: { x: moveEvent.clientX, y: moveEvent.clientY },
        };
        boundaryDraftRef.current = updated;
        return updated;
      });
    };

    const onPointerUp = () => {
      const latestDraft = boundaryDraftRef.current;
      clearBoundaryPointerListeners();
      if (latestDraft) finishBoundaryDrawRef.current(latestDraft);
    };

    boundaryPointerMoveRef.current = onPointerMove;
    boundaryPointerUpRef.current = onPointerUp;
    window.addEventListener('pointermove', onPointerMove);
    window.addEventListener('pointerup', onPointerUp);
    setSelectedNode(null);
  }, [boundaryDrawMode, clearBoundaryPointerListeners]);

  const finishBoundaryDraw = useCallback((draft) => {
    if (!draft) return;

    const width = Math.abs((draft.endClient?.x || 0) - (draft.startClient?.x || 0));
    const height = Math.abs((draft.endClient?.y || 0) - (draft.startClient?.y || 0));
    if (width < 12 || height < 12) {
      setBoundaryDraft(null);
      toast.info('Drag a larger area to create a boundary.');
      return;
    }

    const containerRect = flowContainerRef.current?.getBoundingClientRect();
    if (!containerRect) {
      setBoundaryDraft(null);
      return;
    }

    const startFlow = project({
      x: draft.startClient.x - containerRect.left,
      y: draft.startClient.y - containerRect.top,
    });
    const endFlow = project({
      x: draft.endClient.x - containerRect.left,
      y: draft.endClient.y - containerRect.top,
    });
    const rect = boundaryFlowRect(startFlow, endFlow);

    const memberIds = nodesRef.current
      .filter((node) => {
        if (!node || node.hidden) return false;
        const center = nodeCenterInFlow(node);
        return pointInRect(center, rect);
      })
      .map((node) => node.id);

    if (memberIds.length < 1) {
      toast.info('Boundary requires at least one node inside the draw area.');
      setBoundaryDraft(null);
      return;
    }

    const boundaryId = `boundary-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    setBoundaries((prev) => ([
      ...prev,
      {
        id: boundaryId,
        name: `Boundary ${prev.length + 1}`,
        memberIds,
      },
    ]));
    dirtyRef.current = true;
    setBoundaryDrawMode(false);
    setBoundaryDraft(null);
    toast.success('Boundary created.');
  }, [project, toast]);

  useEffect(() => {
    finishBoundaryDrawRef.current = finishBoundaryDraw;
  }, [finishBoundaryDraw]);

  const handlePanePointerUp = useCallback(() => {
    if (!boundaryDraft) return;
    const latestDraft = boundaryDraftRef.current || boundaryDraft;
    clearBoundaryPointerListeners();
    finishBoundaryDraw(latestDraft);
  }, [boundaryDraft, clearBoundaryPointerListeners, finishBoundaryDraw]);

  const beginBoundaryRename = useCallback((boundaryId, currentName) => {
    setEditingBoundaryId(boundaryId);
    setEditingBoundaryName(currentName);
  }, []);

  const commitBoundaryRename = useCallback(() => {
    if (!editingBoundaryId) return;
    const nextName = editingBoundaryName.trim();
    if (!nextName) {
      setEditingBoundaryId(null);
      setEditingBoundaryName('');
      return;
    }
    setBoundaries((prev) => prev.map((boundary) => (
      boundary.id === editingBoundaryId
        ? { ...boundary, name: nextName }
        : boundary
    )));
    dirtyRef.current = true;
    setEditingBoundaryId(null);
    setEditingBoundaryName('');
  }, [editingBoundaryId, editingBoundaryName]);

  // ── Edge interaction handlers ───────────────────────────────────────────────

  const handleEdgeContextMenu = useCallback((event, _edge) => {
    event.preventDefault();
    setEdgeMenu({ edgeId: _edge.id, x: event.clientX, y: event.clientY });
  }, []);

  const handleControlPointChange = useCallback((edgeId, clientPos) => {
    const containerRect = flowContainerRef.current?.getBoundingClientRect() ?? { left: 0, top: 0 };
    const flowPos = project({ x: clientPos.x - containerRect.left, y: clientPos.y - containerRect.top });
    const updated = {
      ...edgeOverridesRef.current,
      [edgeId]: { ...edgeOverridesRef.current[edgeId], control_point: flowPos },
    };
    edgeOverridesRef.current = updated;
    setEdgeOverrides(updated);
    setEdges(prev => prev.map(e =>
      e.id === edgeId ? { ...e, data: { ...e.data, controlPoint: flowPos } } : e
    ));
    dirtyRef.current = true;
  }, [project, setEdges]);

  const handleEdgeAnchorChange = useCallback((edgeId, which, side) => {
    const key = which === 'source' ? 'source_side' : 'target_side';
    let updated;
    if (side === 'auto') {
      // Remove override for this side — auto-routing takes over
      const existing = { ...edgeOverridesRef.current[edgeId] };
      delete existing[key];
      if (Object.keys(existing).length === 0) {
        updated = omitKey(edgeOverridesRef.current, edgeId);
      } else {
        updated = { ...edgeOverridesRef.current, [edgeId]: existing };
      }
    } else {
      updated = {
        ...edgeOverridesRef.current,
        [edgeId]: { ...edgeOverridesRef.current[edgeId], [key]: side },
      };
    }
    edgeOverridesRef.current = updated;
    setEdgeOverrides(updated);
    setEdges(prev => applyEdgeSides(nodesRef.current, prev, updated));
    dirtyRef.current = true;
    setEdgeMenu(null);
  }, [setEdges]);

  const handleClearBend = useCallback((edgeId) => {
    const existing = { ...edgeOverridesRef.current[edgeId] };
    delete existing.control_point;
    const updated = Object.keys(existing).length === 0
      ? omitKey(edgeOverridesRef.current, edgeId)
      : { ...edgeOverridesRef.current, [edgeId]: existing };
    edgeOverridesRef.current = updated;
    setEdgeOverrides(updated);
    setEdges(prev => prev.map(e =>
      e.id === edgeId ? { ...e, data: { ...e.data, controlPoint: null } } : e
    ));
    dirtyRef.current = true;
    setEdgeMenu(null);
  }, [setEdges]);

  // ── Drag-to-connect / drag-to-reconnect handlers ──────────────────────────

  const handlePanePointerMove = useCallback((event) => {
    const rect = flowContainerRef.current?.getBoundingClientRect();
    if (!rect) return;
    const next = clampPickerPosition(event.clientX - rect.left, event.clientY - rect.top);
    lastPointerRef.current = next;
    setBoundaryDraft((draft) => {
      if (!draft) return draft;
      return {
        ...draft,
        endClient: { x: event.clientX, y: event.clientY },
      };
    });
  }, [clampPickerPosition]);

  const openConnectionPicker = useCallback((mode, connection, oldEdge = null) => {
    const pos = clampPickerPosition(lastPointerRef.current.x, lastPointerRef.current.y);
    setPendingConnection({
      mode,
      oldEdge,
      connection,
      x: pos.x,
      y: pos.y,
    });
  }, [clampPickerPosition]);

  const findCreatedEdgeId = useCallback(async (linkMeta, fallbackConnection) => {
    const topoRes = await graphApi.topology(getTopologyParams());
    const edgeList = topoRes?.data?.edges || [];
    const nodeIds = inferEdgeNodeIdsFromMeta(linkMeta, fallbackConnection.source, fallbackConnection.target);
    return getNewestEdgeId(edgeList, (edge) => {
      const relation = edge?.data?.relation || edge?.relation;
      const relationMatch = !linkMeta?.relation || relation === linkMeta.relation;
      const prefixMatch = !linkMeta?.edgePrefix || edge.id.startsWith(linkMeta.edgePrefix);
      return edge.source === nodeIds.sourceNodeId && edge.target === nodeIds.targetNodeId && relationMatch && prefixMatch;
    });
  }, [getNewestEdgeId, getTopologyParams]);

  const persistEdgeType = useCallback(async (edgeId, connectionType) => {
    if (!edgeId) return false;
    try {
      await graphApi.updateEdgeType(edgeId, connectionType);
      return true;
    } catch (err) {
      console.warn('Could not persist edge type:', err?.message);
      return false;
    }
  }, []);

  const createConnection = useCallback(async (connection, connectionType) => {
    const linkMeta = await createLinkByNodeIds(connection.source, connection.target, nodesRef.current);
    if (linkMeta.updatable) {
      const createdEdgeId = await findCreatedEdgeId(linkMeta, connection);
      if (!createdEdgeId) {
        toast.warn('Connection created, but edge ID lookup failed. Type may not persist.');
      } else if (connectionType !== 'ethernet') {
        await persistEdgeType(createdEdgeId, connectionType);
      }
    } else if (connectionType !== 'ethernet') {
      toast.info('Connection created, but this structural link does not store a connection type.');
    }
  }, [findCreatedEdgeId, persistEdgeType, toast]);

  const reconnectEdge = useCallback(async (oldEdge, connection, connectionType) => {
    if (!oldEdge) return;
    if (oldEdge.source === connection.source && oldEdge.target === connection.target) {
      await persistEdgeType(oldEdge.id, connectionType);
      return;
    }

    const linkMeta = await createLinkByNodeIds(connection.source, connection.target, nodesRef.current);
    if (linkMeta.updatable) {
      const createdEdgeId = await findCreatedEdgeId(linkMeta, connection);
      if (!createdEdgeId) {
        toast.warn('Reconnected link, but edge ID lookup failed. Type may not persist.');
      } else if (connectionType !== 'ethernet') {
        await persistEdgeType(createdEdgeId, connectionType);
      }
    } else if (connectionType !== 'ethernet') {
      toast.info('Reconnected link, but this structural link does not store a connection type.');
    }

    try {
      await unlinkByEdge(oldEdge);
    } catch {
      toast.warn('New connection created, but old link could not be removed.');
    }
  }, [findCreatedEdgeId, persistEdgeType, toast]);

  const handleConnect = useCallback((connection) => {
    if (!connection?.source || !connection?.target) return;
    openConnectionPicker('new', connection);
  }, [openConnectionPicker]);

  const handleEdgeUpdate = useCallback((oldEdge, newConnection) => {
    if (!oldEdge || !newConnection?.source || !newConnection?.target) return;
    openConnectionPicker('reconnect', newConnection, oldEdge);
  }, [openConnectionPicker]);

  const handlePickConnectionType = useCallback(async (requestedType) => {
    if (!pendingConnection) return;
    const current = pendingConnection;
    setPendingConnection(null);

    const connectionType = normalizeConnectionType(requestedType) || 'ethernet';

    try {
      if (current.mode === 'new') {
        await createConnection(current.connection, connectionType);
      } else {
        await reconnectEdge(current.oldEdge, current.connection, connectionType);
      }
      await fetchData();
    } catch (err) {
      toast.error(err.message || 'Connection update failed.');
      await fetchData();
    }
  }, [createConnection, fetchData, pendingConnection, reconnectEdge, toast]);

  const handleNodeDragStop = useCallback((_event, _node, draggedNodes) => {
    setEdges(prev => applyEdgeSides(draggedNodes, prev, edgeOverridesRef.current, _node.id));
    dirtyRef.current = true;
  }, [setEdges]);

  // Keep edgeCallbacksRef.current up-to-date so SmartEdge always calls the
  // latest version of handleControlPointChange without needing to re-render.
  edgeCallbacksRef.current = { onControlPointChange: handleControlPointChange };

  return (
    <MapEdgeCallbacksContext.Provider value={edgeCallbacksRef}>
    <div className="page map-page" style={{ height: 'calc(100vh - 60px)', display: 'flex', flexDirection: 'column', position: 'relative' }}>
      <style>{`@keyframes tm-pulse { 0%,100% { opacity:1; } 50% { opacity:0.55; } }`}</style>
      {/* Header + Toolbar */}
      <div className="page-header" style={{ marginBottom: 0, paddingBottom: 10, borderBottom: '1px solid var(--color-border)', flexWrap: 'wrap', gap: 8, position: 'sticky', top: 0, zIndex: 40, background: 'color-mix(in srgb, var(--color-bg) 88%, transparent)', backdropFilter: 'blur(6px)' }}>
        <h2 style={{ marginRight: 16 }}>Topology</h2>

        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', flex: 1 }}>
          {/* Environment */}
          <select
            value={envFilter}
            onChange={(e) => setEnvFilter(e.target.value ? Number(e.target.value) : '')}
            style={{ padding: '5px 10px', borderRadius: 6, border: '1px solid var(--color-border)', background: 'var(--color-bg)', color: 'var(--color-text)', fontSize: 12 }}
          >
            <option value="">All Environments</option>
            {environmentsList.map((e) => (
              <option key={e.id} value={e.id} style={e.color ? { color: e.color } : {}}>
                {e.name}
              </option>
            ))}
          </select>

          {/* Tag filter */}
          <input
            type="text"
            placeholder="Filter by tag…"
            value={tagFilter}
            onChange={e => setTagFilter(e.target.value)}
            style={{ padding: '5px 10px', borderRadius: 6, border: '1px solid var(--color-border)', background: 'var(--color-bg)', color: 'var(--color-text)', fontSize: 12, width: 130 }}
          />

          {/* Node type toggles */}
          <span style={{ color: 'var(--color-text-muted)', fontSize: 11, borderLeft: '1px solid var(--color-border)', paddingLeft: 8 }}>Show:</span>
          {Object.entries(NODE_STYLES).map(([type, style]) => (
            <button
              key={type}
              onClick={() => setIncludeTypes(prev => ({ ...prev, [type]: !prev[type] }))}
              style={{
                padding: '3px 8px',
                borderRadius: 4,
                border: `1px solid ${style.borderColor}`,
                background: includeTypes[type] ? style.background : 'transparent',
                color: includeTypes[type] ? '#fff' : style.background,
                fontSize: 11,
                cursor: 'pointer',
                transition: 'all 0.15s',
              }}
            >
              {NODE_TYPE_LABELS[type]}
            </button>
          ))}

          {/* Hardware sub-role chips */}
          {includeTypes.hardware && (
            <>
              <span style={{ color: 'var(--color-text-muted)', fontSize: 11, borderLeft: '1px solid var(--color-border)', paddingLeft: 8 }}>Role:</span>
              {[
                { value: 'ups',          label: 'UPS' },
                { value: 'pdu',          label: 'PDU' },
                { value: 'access_point', label: 'AP' },
                { value: 'sbc',          label: 'SBC' },
              ].map(({ value, label }) => (
                <button
                  key={value}
                  onClick={() => setHwRoleFilter(prev => prev === value ? null : value)}
                  style={{
                    padding: '3px 8px', borderRadius: 4, fontSize: 11, cursor: 'pointer',
                    border: '1px solid #4a7fa5',
                    background: hwRoleFilter === value ? '#4a7fa5' : 'transparent',
                    color: hwRoleFilter === value ? '#fff' : '#4a7fa5',
                    transition: 'all 0.15s',
                  }}
                >
                  {label}
                </button>
              ))}
            </>
          )}

          {/* Divider */}
          <span style={{ color: 'var(--color-text-muted)', borderLeft: '1px solid var(--color-border)', paddingLeft: 8, fontSize: 11 }}>Layout:</span>
          <select
            value={layoutEngine}
            onChange={(e) => applyLayout(e.target.value)}
            style={{ padding: '5px 10px', borderRadius: 6, border: '1px solid var(--color-border)', background: 'var(--color-bg)', color: 'var(--color-text)', fontSize: 12 }}
          >
            <option value="dagre">Dagre (Hierarchical)</option>
            <option value="force">Force Directed</option>
            <option value="tree">Tree</option>
            <option value="manual">Manual / Saved</option>
          </select>

          <button
            onClick={() => setCloudViewEnabled(!cloudViewEnabled)}
            style={{
              padding: '5px 10px',
              borderRadius: 6,
              border: `1px solid ${cloudViewEnabled ? 'var(--color-primary)' : 'var(--color-border)'}`,
              background: cloudViewEnabled ? 'rgba(0, 212, 255, 0.1)' : 'var(--color-bg)',
              color: cloudViewEnabled ? 'var(--color-primary)' : 'var(--color-text)',
              fontSize: 12,
              cursor: 'pointer',
              transition: 'all 0.2s',
            }}
          >
            {cloudViewEnabled ? '☁ Disable Cloud View' : '☁ Enable Cloud View'}
          </button>

          <button className="btn btn-primary" onClick={saveLayout} disabled={loading} style={{ fontSize: 12, padding: '5px 12px' }}>
            {loading ? 'Loading…' : 'Save Positions'}
          </button>
          <button className="btn" onClick={fetchData} disabled={loading} style={{ fontSize: 12, padding: '5px 12px' }}>
            Refresh
          </button>
          <button
            type="button"
            className="btn"
            onClick={() => {
              setBoundaryDrawMode((prev) => !prev);
              setBoundaryDraft(null);
            }}
            style={{
              fontSize: 12,
              padding: '5px 12px',
              borderColor: boundaryDrawMode ? 'var(--color-primary)' : undefined,
              color: boundaryDrawMode ? 'var(--color-primary)' : undefined,
            }}
          >
            {boundaryDrawMode ? 'Cancel Boundary Draw' : 'Draw Boundary'}
          </button>
          {pendingDiscoveries > 0 && (
            <button
              type="button"
              onClick={() => navigate('/discovery?tab=review')}
              style={{
                display: 'flex', alignItems: 'center', gap: 5,
                padding: '4px 10px', borderRadius: 5, border: 'none',
                background: 'rgba(245,158,11,0.18)', color: '#f59e0b',
                cursor: 'pointer', fontSize: 11, fontWeight: 600,
              }}
            >
              🔍 {pendingDiscoveries} pending
            </button>
          )}
          {lastSaved && <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>Saved: {new Date(lastSaved).toLocaleTimeString()}</span>}
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div style={{ background: 'rgba(243,139,168,0.15)', border: '1px solid #f38ba8', color: '#f38ba8', padding: '6px 12px', fontSize: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span>{error}</span>
          <button onClick={() => setError(null)} style={{ background: 'none', border: 'none', color: '#f38ba8', cursor: 'pointer' }}><X size={14} /></button>
        </div>
      )}

      {/* Graph canvas */}
      <div ref={flowContainerRef} style={{ flex: 1, position: 'relative', background: 'var(--color-bg)' }}>
        {boundaryRenderData.length > 0 && (
          <div style={{ position: 'absolute', inset: 0, zIndex: 9, pointerEvents: 'none' }}>
            <svg width="100%" height="100%" style={{ display: 'block', overflow: 'visible' }}>
              {boundaryRenderData.map((boundary) => (
                <path
                  key={boundary.id}
                  d={boundary.path}
                  fill="rgba(70, 170, 220, 0.12)"
                  stroke="rgba(95, 205, 255, 0.75)"
                  strokeWidth={2}
                  strokeDasharray="8 6"
                  vectorEffect="non-scaling-stroke"
                />
              ))}
            </svg>
          </div>
        )}

        {boundaryRenderData.length > 0 && (
          <div style={{ position: 'absolute', inset: 0, zIndex: 12, pointerEvents: 'none' }}>
            {boundaryRenderData.map((boundary) => (
              <div
                key={`label-${boundary.id}`}
                style={{
                  position: 'absolute',
                  left: boundary.anchorScreen.x,
                  top: boundary.anchorScreen.y,
                  transform: 'translate(-50%, -50%)',
                  pointerEvents: 'auto',
                }}
              >
                {editingBoundaryId === boundary.id ? (
                  <input
                    autoFocus
                    value={editingBoundaryName}
                    onChange={(event) => setEditingBoundaryName(event.target.value)}
                    onBlur={commitBoundaryRename}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter') commitBoundaryRename();
                      if (event.key === 'Escape') {
                        setEditingBoundaryId(null);
                        setEditingBoundaryName('');
                      }
                    }}
                    style={{
                      minWidth: 140,
                      borderRadius: 999,
                      border: '1px solid rgba(95, 205, 255, 0.9)',
                      background: 'rgba(7, 18, 33, 0.92)',
                      color: 'var(--color-text)',
                      padding: '3px 10px',
                      fontSize: 12,
                      textAlign: 'center',
                    }}
                  />
                ) : (
                  <button
                    type="button"
                    onDoubleClick={() => beginBoundaryRename(boundary.id, boundary.name)}
                    style={{
                      borderRadius: 999,
                      border: '1px solid rgba(95, 205, 255, 0.75)',
                      background: 'rgba(7, 18, 33, 0.72)',
                      color: 'var(--color-text)',
                      padding: '2px 10px',
                      fontSize: 12,
                      cursor: 'text',
                    }}
                    title="Double-click to rename boundary"
                  >
                    {boundary.name}
                  </button>
                )}
              </div>
            ))}
          </div>
        )}

        {boundaryDrawMode && (
          <div style={{ position: 'absolute', top: 10, left: '50%', transform: 'translateX(-50%)', zIndex: 20, pointerEvents: 'none' }}>
            <div style={{ padding: '5px 10px', borderRadius: 999, border: '1px solid var(--color-primary)', background: 'rgba(0,0,0,0.45)', color: 'var(--color-text)', fontSize: 12 }}>
              Drag on the canvas to draw a boundary around nodes
            </div>
          </div>
        )}

        {boundaryDraft && (() => {
          const left = Math.min(boundaryDraft.startClient.x, boundaryDraft.endClient.x);
          const top = Math.min(boundaryDraft.startClient.y, boundaryDraft.endClient.y);
          const width = Math.abs(boundaryDraft.endClient.x - boundaryDraft.startClient.x);
          const height = Math.abs(boundaryDraft.endClient.y - boundaryDraft.startClient.y);
          return (
            <div
              style={{
                position: 'fixed',
                left,
                top,
                width,
                height,
                border: '1px dashed rgba(95, 205, 255, 0.95)',
                background: 'rgba(70, 170, 220, 0.12)',
                zIndex: 25,
                pointerEvents: 'none',
              }}
            />
          );
        })()}

        <ReactFlow
          className={boundaryDrawMode ? 'map-draw-mode' : ''}
          style={{ zIndex: 5, cursor: boundaryDrawMode ? 'crosshair' : 'default' }}
          nodeTypes={NODE_TYPES}
          edgeTypes={EDGE_TYPES}
          nodes={nodes}
          edges={edges}
          onNodesChange={(changes) => {
            onNodesChange(changes);
            if (changes.some(c => c.type === 'position' && c.dragging)) dirtyRef.current = true;
          }}
          onEdgesChange={onEdgesChange}
          onNodeDragStop={handleNodeDragStop}
          onNodeMouseEnter={handleNodeMouseEnter}
          onNodeMouseLeave={handleNodeMouseLeave}
          onNodeClick={handleNodeClick}
          onNodeContextMenu={handleNodeContextMenu}
          onPaneContextMenu={handlePaneContextMenu}
          onPaneMouseDown={handlePanePointerDown}
          onPaneMouseUp={handlePanePointerUp}
          onEdgeContextMenu={handleEdgeContextMenu}
          onConnect={handleConnect}
          onEdgeUpdate={handleEdgeUpdate}
          onPaneMouseMove={handlePanePointerMove}
          connectionLineType="smoothstep"
          connectionRadius={14}
          defaultEdgeOptions={{ style: { strokeWidth: 3, stroke: '#888' } }}
          onPaneClick={() => { setEdgeMenu(null); setPendingConnection(null); handlePaneClick(); }}
          fitView
          minZoom={0.1}
          panOnDrag={!boundaryDrawMode}
          panOnScroll={!boundaryDrawMode}
          zoomOnScroll={!boundaryDrawMode}
          zoomOnPinch={!boundaryDrawMode}
          zoomOnDoubleClick={!boundaryDrawMode}
          preventScrolling  /* keep page from scrolling when pointer is over map */
        >
          {/* Loading overlay */}
          {loading && nodes.length === 0 && (
            <div style={{
              position: 'absolute',
              inset: 0,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              background: 'var(--color-bg)',
              zIndex: 100,
            }}>
              <div className="login-spin" style={{ width: 48, height: 48, border: '4px solid var(--color-border)', borderTopColor: 'var(--color-primary)', borderRadius: '50%' }} />
              <p style={{ marginTop: 16, color: 'var(--color-text-muted)', fontSize: 14 }}>Loading topology…</p>
            </div>
          )}

          {/* Legend */}
          <Panel position="top-left" style={{ zIndex: 35 }}>
            {legendOpen ? (
              <div style={{
                background: 'var(--color-surface)',
                padding: 12,
                borderRadius: 8,
                fontSize: 11,
                color: 'var(--color-text)',
                border: '1px solid var(--color-border)',
                minWidth: 238,
                boxShadow: '0 4px 16px rgba(0,0,0,0.3)',
                position: 'relative'
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                  <div style={{ fontWeight: 600, color: 'var(--color-text-muted)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Legend</div>
                  <button
                    onClick={() => setLegendOpen(false)}
                    style={{ background: 'none', border: 'none', color: 'var(--color-text-muted)', cursor: 'pointer', padding: 2, display: 'flex' }}
                  >
                    <X size={14} />
                  </button>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                  <div>
                    <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.05em', textTransform: 'uppercase', color: 'var(--color-text-muted)', marginBottom: 6 }}>Connection Types</div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                      {CONNECTION_TYPE_LEGEND.map((entry) => (
                        <div key={entry.key} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <span style={{ width: 10, height: 10, borderRadius: '50%', background: entry.color, boxShadow: `0 0 8px ${entry.color}88` }} />
                          <span>{entry.label}</span>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div>
                    <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.05em', textTransform: 'uppercase', color: 'var(--color-text-muted)', marginBottom: 6 }}>Node Types</div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 10 }}>
                      {Object.entries(NODE_STYLES).map(([type, style]) => (
                        <div key={type} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <div style={{ width: 10, height: 10, background: style.background, borderRadius: 2, border: `1px solid ${style.borderColor}` }} />
                          <span style={{ textTransform: 'capitalize', color: includeTypes[type] ? 'var(--color-text)' : 'var(--color-text-muted)' }}>{type}</span>
                        </div>
                      ))}
                    </div>

                    <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.05em', textTransform: 'uppercase', color: 'var(--color-text-muted)', marginBottom: 6 }}>Status</div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                      {STATUS_LEGEND.map((entry) => (
                        <div key={entry.key} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <span style={{ width: 9, height: 9, borderRadius: '50%', background: entry.color, boxShadow: `0 0 8px ${entry.color}88` }} />
                          <span>{entry.label}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <button
                onClick={() => setLegendOpen(true)}
                style={{
                  background: 'var(--color-surface)',
                  padding: '6px 12px',
                  borderRadius: 20,
                  fontSize: 11,
                  fontWeight: 600,
                  color: 'var(--color-text)',
                  border: '1px solid var(--color-border)',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  boxShadow: '0 2px 8px rgba(0,0,0,0.2)'
                }}
              >
                <span>Legend</span>
                <span style={{ fontSize: 10 }}>▼</span>
              </button>
            )}
          </Panel>
          <Controls style={{ zIndex: 35 }} />
          <Background color={bgGridColor} gap={24} size={1} />
        </ReactFlow>

        <WifiOverlay nodes={nodes} />

        {pendingConnection && (
          <ConnectionTypePicker
            x={pendingConnection.x}
            y={pendingConnection.y}
            onSelect={handlePickConnectionType}
            onCancel={() => setPendingConnection(null)}
          />
        )}

        {/* Empty-canvas hint */}
        {!loading && nodes.length === 0 && !error && settings?.show_page_hints && (
          <div
            className="info-tip"
            style={{
              position: 'absolute',
              top: '50%',
              left: '50%',
              transform: 'translate(-50%, -50%)',
              maxWidth: 400,
              textAlign: 'center',
              pointerEvents: 'none',
              zIndex: 10,
            }}
          >
            💡 Your map is empty. Add <strong>Hardware</strong>, <strong>Compute Units</strong>,{' '}
            <strong>Services</strong>, or <strong>External Nodes</strong> from their pages to see
            them appear here.
          </div>
        )}

        {/* Hover tooltip */}
        {tooltip && (
          <div
            style={{
              position: 'fixed',
              left: tooltip.x,
              top: tooltip.y,
              background: 'var(--color-surface)',
              border: '1px solid var(--color-border)',
              borderRadius: 6,
              padding: '8px 12px',
              fontSize: 12,
              color: 'var(--color-text)',
              pointerEvents: 'none',
              zIndex: 9999,
              maxWidth: 280,
              boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
            }}
          >
            <div style={{ fontWeight: 600, marginBottom: 4 }}>{tooltip.node.data.label}</div>
            <div style={{ color: 'var(--color-text-muted)', marginBottom: 2 }}>
              Type: <span style={{ color: NODE_STYLES[tooltip.node.originalType]?.background }}>{NODE_TYPE_LABELS[tooltip.node.originalType] || tooltip.node.originalType}</span>
            </div>
            {tooltip.node.originalType === 'hardware' && tooltip.node._hwRole && (
              <div style={{ color: 'var(--color-text-muted)', marginBottom: 2 }}>
                Role: <span style={{ color: 'var(--color-text)' }}>{tooltip.node._hwRole}</span>
              </div>
            )}
            {/* IP / CIDR */}
            {(tooltip.node.data.ip_address || tooltip.node.data.cidr) && (
              <div style={{ fontFamily: 'monospace', fontSize: 11, color: 'var(--color-primary)', marginBottom: 2 }}>
                {tooltip.node.data.ip_address || tooltip.node.data.cidr}
              </div>
            )}
            {tooltip.node.originalType === 'service' && buildServiceHttpAddress(tooltip.node) && (
              <div style={{ fontFamily: 'monospace', fontSize: 11, color: 'var(--color-primary)', marginBottom: 2 }}>
                {buildServiceHttpAddress(tooltip.node)}
              </div>
            )}
            {['hardware', 'compute'].includes(tooltip.node.originalType) && (() => {
              const hosted = getHostedServiceRows(tooltip.node, nodes, edges);
              if (hosted.length === 0) return null;
              return (
                <div style={{ marginTop: 6, fontSize: 11 }}>
                  <div style={{ color: 'var(--color-text-muted)', marginBottom: 3 }}>Hosted Services</div>
                  {hosted.slice(0, 5).map((service) => (
                    <div key={service.id} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginBottom: 2 }}>
                      <span style={{ color: 'var(--color-text)' }}>{service.name}</span>
                      {service.location && <span style={{ color: 'var(--color-primary)', fontFamily: 'monospace' }}>{service.location}</span>}
                    </div>
                  ))}
                </div>
              );
            })()}
            {/* Storage summary (hardware) */}
            {tooltip.node.data.storage_summary && (() => {
              const s = tooltip.node.data.storage_summary;
              const tb = s.total_gb >= 1024 ? `${(s.total_gb / 1024).toFixed(1)}TB` : `${s.total_gb}GB`;
              const types = s.types?.join(', ') || '';
              const usedPct = s.used_gb != null && s.total_gb > 0
                ? `${Math.round(s.used_gb / s.total_gb * 100)}% used`
                : null;
              const parts = [usedPct, types].filter(Boolean).join(', ');
              return (
                <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 2 }}>
                  💾 {tb} total{parts ? ` (${parts})` : ''}
                  {s.primary_pool && <span> · {s.primary_pool}</span>}
                </div>
              );
            })()}
            {/* Storage allocated (compute) */}
            {tooltip.node.data.storage_allocated?.disk_gb && (
              <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 2 }}>
                💾 {tooltip.node.data.storage_allocated.disk_gb} GB disk
                {tooltip.node.data.storage_allocated.storage_pools?.length > 0 &&
                  <span> · {tooltip.node.data.storage_allocated.storage_pools.join(', ')}</span>}
              </div>
            )}
            {/* Capacity (storage nodes) */}
            {tooltip.node.data.capacity_gb && (
              <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 2 }}>
                💾 {tooltip.node.data.capacity_gb >= 1024
                  ? `${(tooltip.node.data.capacity_gb / 1024).toFixed(1)} TB`
                  : `${tooltip.node.data.capacity_gb} GB`} capacity
                {tooltip.node.data.used_gb != null && tooltip.node.data.capacity_gb > 0 &&
                  <span> ({Math.round(tooltip.node.data.used_gb / tooltip.node.data.capacity_gb * 100)}% used)</span>}
              </div>
            )}
            {tooltip.node._tags?.length > 0 && (
              <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 4 }}>
                {tooltip.node._tags.map(t => (
                  <span key={t} style={{ background: 'var(--color-glow)', color: 'var(--color-primary)', borderRadius: 3, padding: '1px 5px', fontSize: 10 }}>{t}</span>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Node context menu */}
        {contextMenu && (
          <ContextMenu
            position={{ x: contextMenu.x, y: contextMenu.y }}
            node={contextMenu.node}
            nodes={nodes}
            onClose={() => setContextMenu(null)}
            onAction={handleContextAction}
          />
        )}
        
        {/* Create Node Modal */}
        <CreateNodeModal
          isOpen={createNodeModal.isOpen}
          position={createNodeModal.position}
          onClose={() => setCreateNodeModal({ isOpen: false, position: null })}
          onConfirm={handleCreateNode}
        />

        {iconPickerOpen && iconPickerNode && (
          <IconPickerModal
            currentSlug={iconPickerNode.data?.icon_slug ?? null}
            onSelect={handleIconPick}
            onClose={() => {
              setIconPickerOpen(false);
              setIconPickerNode(null);
            }}
          />
        )}

        {quickActionModal && globalThis.document?.body && createPortal(
          <div
            className="modal-overlay"
            style={{ position: 'fixed', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999 }}
          >
            <dialog
              open
              className="modal"
              aria-labelledby="quick-action-title"
              style={{ width: 420, margin: 0 }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                <h3 id="quick-action-title">{quickActionModal.mode === 'alias' ? 'Set Alias' : 'Update Status'}</h3>
                <button
                  type="button"
                  className="btn"
                  aria-label="Close quick action dialog"
                  onClick={() => {
                    setQuickActionModal(null);
                    setQuickActionValue('');
                  }}
                  style={{ width: 28, height: 28, padding: 0, borderRadius: 999, display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
                >
                  <X size={14} />
                </button>
              </div>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  handleSubmitQuickAction();
                }}
              >
                <div style={{ marginTop: 12 }}>
                  <div style={{ marginBottom: 8, fontSize: 12, color: 'var(--color-text-muted)' }}>
                    {quickActionModal.label}
                  </div>
                  {quickActionModal.mode === 'alias' ? (
                    <input
                      className="input"
                      aria-label="Alias value"
                      style={{
                        width: '100%',
                        background: 'var(--color-surface)',
                        color: 'var(--color-text)',
                        border: '1px solid var(--color-border)',
                        borderRadius: 'var(--radius)',
                        padding: '6px 10px',
                      }}
                      autoFocus
                      value={quickActionValue}
                      onChange={(e) => setQuickActionValue(e.target.value)}
                      placeholder="Enter alias"
                    />
                  ) : (
                    <select
                      className="filter-select"
                      aria-label="Status value"
                      autoFocus
                      value={quickActionValue}
                      onChange={(e) => setQuickActionValue(e.target.value)}
                      style={{
                        width: '100%',
                        background: 'var(--color-surface)',
                        color: 'var(--color-text)',
                        border: '1px solid var(--color-border)',
                        borderRadius: 'var(--radius)',
                        padding: '6px 10px',
                      }}
                    >
                      {(quickActionModal.allowed || []).map((value) => (
                        <option key={value} value={value}>
                          {STATUS_OPTION_LABEL[value] || value}
                        </option>
                      ))}
                    </select>
                  )}
                </div>

                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 18 }}>
                  <button
                    type="button"
                    className="btn"
                    onClick={() => {
                      setQuickActionModal(null);
                      setQuickActionValue('');
                    }}
                    disabled={quickActionSaving}
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="btn btn-primary"
                    disabled={quickActionSaving}
                  >
                    {quickActionSaving ? 'Saving…' : 'Save'}
                  </button>
                </div>
              </form>
            </dialog>
          </div>,
          globalThis.document.body,
        )}

        <BulkQuickCreateModal
          open={quickCreateModal.open}
          modal={quickCreateModal}
          rows={quickCreateRows}
          rowErrors={quickCreateRowErrors}
          saving={quickCreateSaving}
          onSubmit={handleBulkQuickCreateSubmit}
          onUpdateRow={updateQuickCreateRow}
          onAddRow={addQuickCreateRow}
          onRemoveRow={removeQuickCreateRow}
          onClose={() => {
            setQuickCreateModal({ open: false, mode: null, title: '', sourceLabel: '', initialValues: {} });
            setQuickCreateRows([]);
            setQuickCreateRowErrors({});
          }}
        />

        <FormModal
          open={roleModal.open}
          title={roleModal.isEdit ? 'Edit Role' : 'Designate Role'}
          fields={[
            {
              name: 'role',
              label: `Role for ${roleModal.nodeLabel}`,
              type: 'select',
              required: true,
              options: HARDWARE_ROLES,
            },
          ]}
          initialValues={{ role: roleModal.currentRole || '' }}
          onSubmit={handleSubmitRoleModal}
          onValidate={(values) => {
            const errors = {};
            if (!values.role) errors.role = 'Role is required.';
            return errors;
          }}
          onClose={() => setRoleModal({ open: false, nodeRefId: null, nodeLabel: '', currentRole: '', isEdit: false })}
          entityType="hardware"
          entityId={roleModal.nodeRefId}
        />

        <ConfirmDialog
          open={confirmState.open}
          message={confirmState.message}
          onConfirm={confirmState.onConfirm || (() => {})}
          onCancel={() => setConfirmState((s) => ({ ...s, open: false }))}
        />

        <DeleteConflictModal
          modal={deleteConflictModal}
          onCancel={() => setDeleteConflictModal((m) => ({ ...m, open: false, forcing: false }))}
          onForceRemove={forceRemoveDeleteConflicts}
        />

        {/* Edge anchor context menu */}
        {edgeMenu && (() => {
          const menuW = 200;
          const menuH = 200;
          const ex = Math.min(edgeMenu.x, window.innerWidth  - menuW - 8);
          const ey = Math.min(edgeMenu.y, window.innerHeight - menuH - 8);
          const currentOverride = edgeOverrides[edgeMenu.edgeId] || {};
          const SIDES = ['auto', 'top', 'right', 'bottom', 'left'];
          return (
            <div
              role="menu"
              tabIndex={-1}
              style={{
                position: 'fixed', left: ex, top: ey, zIndex: 1001,
                background: 'var(--color-surface)', border: '1px solid var(--color-border)',
                borderRadius: 8, minWidth: menuW, boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
                overflow: 'hidden', userSelect: 'none',
              }}
              onMouseDown={e => e.stopPropagation()}
            >
              <div style={{ padding: '7px 12px 5px', borderBottom: '1px solid var(--color-border)', fontSize: 10, color: 'var(--color-text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                Edge Anchors
              </div>
              <div style={{ padding: '4px 12px 2px', fontSize: 11, color: 'var(--color-text-muted)' }}>Source side</div>
              <div style={{ display: 'flex', gap: 4, padding: '2px 12px 6px', flexWrap: 'wrap' }}>
                {SIDES.map(s => (
                  <button key={s} onClick={() => handleEdgeAnchorChange(edgeMenu.edgeId, 'source', s)}
                    style={{ padding: '2px 8px', borderRadius: 4, border: '1px solid var(--color-border)', fontSize: 11, cursor: 'pointer',
                      background: (currentOverride.source_side === s || (s === 'auto' && !currentOverride.source_side)) ? 'var(--color-primary)' : 'transparent',
                      color: (currentOverride.source_side === s || (s === 'auto' && !currentOverride.source_side)) ? '#000' : 'var(--color-text)',
                    }}>
                    {s}
                  </button>
                ))}
              </div>
              <div style={{ padding: '4px 12px 2px', fontSize: 11, color: 'var(--color-text-muted)' }}>Target side</div>
              <div style={{ display: 'flex', gap: 4, padding: '2px 12px 6px', flexWrap: 'wrap' }}>
                {SIDES.map(s => (
                  <button key={s} onClick={() => handleEdgeAnchorChange(edgeMenu.edgeId, 'target', s)}
                    style={{ padding: '2px 8px', borderRadius: 4, border: '1px solid var(--color-border)', fontSize: 11, cursor: 'pointer',
                      background: (currentOverride.target_side === s || (s === 'auto' && !currentOverride.target_side)) ? 'var(--color-primary)' : 'transparent',
                      color: (currentOverride.target_side === s || (s === 'auto' && !currentOverride.target_side)) ? '#000' : 'var(--color-text)',
                    }}>
                    {s}
                  </button>
                ))}
              </div>
              <div style={{ height: 1, background: 'var(--color-border)', margin: '2px 0' }} />
              <button onClick={() => handleClearBend(edgeMenu.edgeId)}
                style={{ width: '100%', background: 'transparent', border: 'none', color: 'var(--color-text-muted)', padding: '7px 12px', fontSize: 11, textAlign: 'left', cursor: 'pointer' }}
                onMouseEnter={e => { e.currentTarget.style.background = 'var(--color-glow)'; }}
                onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
              >
                Clear bend point
              </button>
              <button onClick={() => setEdgeMenu(null)}
                style={{ width: '100%', background: 'transparent', border: 'none', color: 'var(--color-text-muted)', padding: '7px 12px', fontSize: 11, textAlign: 'left', cursor: 'pointer' }}
                onMouseEnter={e => { e.currentTarget.style.background = 'var(--color-glow)'; }}
                onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
              >
                Close
              </button>
            </div>
          );
        })()}

        <Sidebar
          node={selectedNode}
          anchor={selectedNodeAnchor}
          relationships={selectedNodeRelationships}
          sysinfo={selectedNodeSysinfo}
          status={selectedNodeStatus}
          onClose={() => setSelectedNode(null)}
          onUplinkChange={handleUplinkChange}
          onOpenInHud={(node) => {
            navigate(NODE_TYPE_ROUTES[node?.originalType] || '/');
          }}
        />
      </div>
    </div>
    </MapEdgeCallbacksContext.Provider>
  );
}

export default function MapPage() {
  return (
    <ReactFlowProvider>
      <MapInternal />
    </ReactFlowProvider>
  );
}
