/**
 * Shared map constants — node styles, edge colors, icon resolution.
 * Extracted from MapPage.jsx so BulkPreviewMap (and other consumers)
 * can reference the same visual vocabulary without importing the full page.
 */

import { getIconEntry } from '../common/IconPickerModal';
import { getVendorIcon } from '../../icons/vendorIcons';

export const NODE_STYLES = {
  cluster:  { background: '#7c3aed', borderColor: '#5b21b6', glowColor: '#a78bfa' },
  hardware: { background: '#4a7fa5', borderColor: '#2c5f7a', glowColor: '#4a7fa5' },
  compute:  { background: '#3a7d44', borderColor: '#1f5c2c', glowColor: '#3a7d44' },
  service:  { background: '#c2601e', borderColor: '#8f4012', glowColor: '#e07030' },
  storage:  { background: '#7b4fa0', borderColor: '#5a3278', glowColor: '#7b4fa0' },
  network:  { background: '#0e8a8a', borderColor: '#0a6060', glowColor: '#0eb8b8' },
  misc:     { background: '#4a5568', borderColor: '#2d3748', glowColor: '#6b7a96' },
  external: { background: '#2196f3', borderColor: '#1565c0', glowColor: '#64b5f6' },
};

export const EDGE_COLORS = {
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

export const NODE_TYPE_LABELS = {
  cluster: 'Cluster',
  hardware: 'Hardware',
  compute: 'Compute',
  service: 'Service',
  storage: 'Storage',
  network: 'Network',
  misc: 'Misc',
  external: 'External',
};

const KIND_ICON = {
  disk: 'hdd', pool: 'nas', dataset: 'nas', share: 'nas',
  container: 'docker',
};

const ROLE_ICON = {
  router: 'router', firewall: 'firewall', switch: 'switch', ap: 'switch', nas: 'nas',
};

/**
 * Resolve the best icon path for a topology node.
 */
export function resolveNodeIcon(type, icon_slug, vendor, kind, role) {
  if (icon_slug)                              return getIconEntry(icon_slug)?.path ?? null;
  if (type === 'hardware' && ROLE_ICON[role]) return getIconEntry(ROLE_ICON[role])?.path ?? null;
  if (type === 'hardware' && vendor)          return getVendorIcon(vendor)?.path ?? null;
  if (type === 'network')                     return getIconEntry('network')?.path ?? null;
  if (kind && KIND_ICON[kind])                return getIconEntry(KIND_ICON[kind])?.path ?? null;
  if (type === 'external')                    return getIconEntry('internet')?.path ?? null;
  return null;
}
