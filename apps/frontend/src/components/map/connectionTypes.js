export const CANONICAL_CONNECTION_TYPES = [
  'ethernet',
  'wireless',
  'tunnel',
  'wg',
  'vpn',
  'ssh',
  'fiber',
  'bgp',
  'vlan',
  'management',
  'backup',
  'heartbeat',
];

export const CONNECTION_TYPE_ALIASES = {
  wireguard: 'wg',
  wifi: 'wireless',
  cluster_member: 'ethernet',
};

export function normalizeConnectionType(type) {
  if (!type) return null;
  const lowered = String(type).trim().toLowerCase();
  const normalized = CONNECTION_TYPE_ALIASES[lowered] || lowered;
  return CANONICAL_CONNECTION_TYPES.includes(normalized) ? normalized : null;
}

export function isConnectionTyped(type) {
  return normalizeConnectionType(type) !== null;
}

export function formatBandwidth(mbps) {
  if (mbps == null || Number.isNaN(Number(mbps))) return null;
  const value = Number(mbps);
  if (value >= 1000) {
    const gbps = value / 1000;
    if (Number.isInteger(gbps)) return `${gbps}G`;
    return `${gbps.toFixed(1).replace(/\.0$/, '')}G`;
  }
  return `${Math.max(0, Math.round(value))}M`;
}

export function computeParticleDuration(baseSpeed = 1, bandwidthMbps = 1000, min = 0.3, max = 20) {
  const safeBase = Number(baseSpeed) > 0 ? Number(baseSpeed) : 1;
  const safeBw = Number(bandwidthMbps) > 0 ? Number(bandwidthMbps) : 1000;
  const duration = 12 / (safeBase * (safeBw / 1000));
  return Math.min(max, Math.max(min, duration));
}

export const CONNECTION_TYPE_OPTIONS = CANONICAL_CONNECTION_TYPES.slice();
