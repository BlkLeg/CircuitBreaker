/**
 * Map v2 Design System Constants
 *
 * Centralised theme tokens for the topology map's status rings,
 * connection lines, and device icons.  Consumed by CustomNode,
 * CustomEdge, and the layout sidebar (Phases 2-5).
 */

// ── Status ring / glow colours ──────────────────────────────────────────────

export const STATUS_COLORS = {
  active: {
    border: '#32b89e',
    glow: 'rgba(50, 184, 158, 0.4)',
    fill: '#262828',
  },
  inactive: {
    border: '#626c71',
    glow: 'rgba(98, 108, 113, 0.2)',
    fill: '#1f2121',
  },
  warning: {
    border: '#e68161',
    glow: 'rgba(230, 129, 97, 0.4)',
    fill: '#262828',
  },
  error: {
    border: '#ff5459',
    glow: 'rgba(255, 84, 89, 0.5)',
    fill: '#262828',
  },
  maintenance: {
    border: '#c09550',
    glow: 'rgba(192, 149, 80, 0.3)',
    fill: '#262828',
  },
  // ── Entity-status aliases (map concrete DB values → visual tokens) ────
  running: { border: '#32b89e', glow: 'rgba(50, 184, 158, 0.4)', fill: '#262828' },
  online: { border: '#32b89e', glow: 'rgba(50, 184, 158, 0.4)', fill: '#262828' },
  healthy: { border: '#32b89e', glow: 'rgba(50, 184, 158, 0.4)', fill: '#262828' },
  stopped: { border: '#626c71', glow: 'rgba(98, 108, 113, 0.2)', fill: '#1f2121' },
  offline: { border: '#626c71', glow: 'rgba(98, 108, 113, 0.2)', fill: '#1f2121' },
  unknown: { border: '#626c71', glow: 'rgba(98, 108, 113, 0.2)', fill: '#1f2121' },
  degraded: { border: '#e68161', glow: 'rgba(230, 129, 97, 0.4)', fill: '#262828' },
  critical: { border: '#ff5459', glow: 'rgba(255, 84, 89, 0.5)', fill: '#262828' },
};

// ── Connection / edge styles ────────────────────────────────────────────────

export const CONNECTION_STYLES = {
  ethernet: {
    stroke: '#32b89e',
    strokeWidth: 2,
    strokeDasharray: null,
    particles: 3,
    baseSpeed: 2.0,
    particleSize: 3,
  },
  wireless: {
    stroke: '#7c5cbf',
    strokeWidth: 2,
    strokeDasharray: '8 4',
    particles: 2,
    baseSpeed: 1.5,
    particleSize: 3,
  },
  tunnel: {
    stroke: '#e68161',
    strokeWidth: 3,
    strokeDasharray: null,
    filter: 'drop-shadow(0 0 4px rgba(230, 129, 97, 0.6))',
    particles: 4,
    baseSpeed: 1.8,
    particleSize: 3.5,
    glow: true,
  },
  wg: {
    stroke: '#c01521',
    strokeWidth: 2.5,
    strokeDasharray: '12 6',
    particles: 2,
    baseSpeed: 1.6,
    particleSize: 3,
  },
  vpn: {
    stroke: '#2074c2',
    strokeWidth: 2,
    strokeDasharray: '4 2',
    particles: 1,
    baseSpeed: 2.2,
    particleSize: 2.5,
  },
  ssh: {
    stroke: '#32b89e',
    strokeWidth: 2,
    strokeDasharray: '2 4',
    particles: 2,
    baseSpeed: 1.9,
    particleSize: 2.5,
  },
  fiber: {
    stroke: '#3b82f6',
    strokeWidth: 2.5,
    strokeDasharray: null,
    filter: 'drop-shadow(0 0 4px rgba(59, 130, 246, 0.6))',
    particles: 4,
    baseSpeed: 2.5,
    particleSize: 3,
    glow: true,
  },
  bgp: {
    stroke: '#8b5cf6',
    strokeWidth: 2,
    strokeDasharray: '6 3',
    particles: 3,
    baseSpeed: 1.4,
    particleSize: 3,
  },
  vlan: {
    stroke: '#f59e0b',
    strokeWidth: 2,
    strokeDasharray: '10 3 2 3',
    particles: 2,
    baseSpeed: 1.7,
    particleSize: 3,
  },
  management: {
    stroke: '#6b7280',
    strokeWidth: 1.5,
    strokeDasharray: '3 3',
    particles: 1,
    baseSpeed: 1.2,
    particleSize: 2,
  },
  backup: {
    stroke: '#10b981',
    strokeWidth: 3,
    strokeDasharray: '15 5',
    particles: 2,
    baseSpeed: 0.8,
    particleSize: 3.5,
  },
  heartbeat: {
    stroke: '#22c55e',
    strokeWidth: 1.5,
    strokeDasharray: '2 4',
    filter: 'drop-shadow(0 0 3px rgba(34, 197, 94, 0.5))',
    particles: 1,
    baseSpeed: 3,
    particleSize: 2.5,
    glow: true,
  },
};

/** Map version for safe lookup by connection type (avoids object injection). */
export const CONNECTION_STYLES_MAP = new Map(Object.entries(CONNECTION_STYLES));

// ── Device role → Lucide icon name mapping ──────────────────────────────────

export const ICON_TYPES = {
  server: 'Server',
  router: 'Router',
  switch: 'Network',
  firewall: 'Shield',
  access_point: 'Wifi',
  nas: 'HardDrive',
  ups: 'Zap',
  pdu: 'Plug',
  laptop: 'Laptop',
  desktop: 'Monitor',
  vm: 'Box',
  container: 'Package',
  cloud: 'Cloud',
};
