import React from 'react';
import { useDiscoveryReadiness } from '../../hooks/useDiscoveryReadiness.js';
import { Toggle } from '../../pages/settings/DiscoverySettingsPage.jsx';

// Structural (platform-level) capabilities that gate whether LAN discovery
// can ever be turned on, regardless of the desired setting.
const LAN_GATING_KEYS = new Set(['arp_l2', 'lan_adjacency']);

const STATE_BADGES = new Map([
  ['ready', { color: '#22c55e', bg: 'rgba(34,197,94,0.12)', label: 'Ready' }],
  ['auto-fixable', { color: '#38bdf8', bg: 'rgba(56,189,248,0.12)', label: 'Auto-heals' }],
  [
    'needs-helper-action',
    { color: '#f59e0b', bg: 'rgba(245,158,11,0.12)', label: 'Needs LAN discovery' },
  ],
  [
    'unavailable-on-platform',
    { color: 'var(--color-text-muted)', bg: 'rgba(255,255,255,0.06)', label: 'Not available here' },
  ],
]);

function relativeTime(iso) {
  if (!iso) return null;
  const diff = Math.floor((Date.now() - new Date(iso)) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function StateBadge({ state }) {
  const s = STATE_BADGES.get(state) || {
    color: 'var(--color-text-muted)',
    bg: 'rgba(255,255,255,0.06)',
    label: state,
  };
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        fontSize: 11,
        fontWeight: 600,
        padding: '2px 8px',
        borderRadius: 20,
        color: s.color,
        background: s.bg,
        flexShrink: 0,
        whiteSpace: 'nowrap',
      }}
    >
      {s.label}
    </span>
  );
}

function CapabilityCard({ capability }) {
  const healedAgo = relativeTime(capability.last_healed_at);
  return (
    <div
      style={{
        padding: '10px 14px',
        border: '1px solid var(--color-border)',
        borderRadius: 8,
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: 8,
        }}
      >
        <span style={{ fontSize: 13, fontWeight: 500 }}>{capability.title}</span>
        <StateBadge state={capability.state} />
      </div>
      <div
        style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 4, lineHeight: 1.5 }}
      >
        {capability.explanation}
      </div>
      {healedAgo && (
        <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 4 }}>
          Last healed {healedAgo}
        </div>
      )}
      {capability.last_error && (
        <div style={{ fontSize: 11, color: '#ef4444', marginTop: 4 }}>
          Last attempt failed: {capability.last_error}
        </div>
      )}
    </div>
  );
}

export default function DiscoveryReadinessPanel({
  lanDiscoveryDesired,
  onToggleLanDiscovery,
  toggleSaving,
}) {
  const { readiness, loading } = useDiscoveryReadiness();

  if (loading || !readiness) {
    return <p style={{ color: 'var(--color-text-muted)', fontSize: 13 }}>Loading readiness…</p>;
  }

  const { helper_installed: helperInstalled, capabilities } = readiness;
  const structurallyUnavailable = capabilities.some(
    (c) => LAN_GATING_KEYS.has(c.key) && c.state === 'unavailable-on-platform'
  );
  const toggleDisabled = structurallyUnavailable || !helperInstalled || toggleSaving;

  let toggleHint = 'Allows ARP-based LAN discovery for MAC resolution and direct LAN reachability.';
  if (structurallyUnavailable) {
    toggleHint = 'LAN discovery is not available on this platform.';
  } else if (!helperInstalled) {
    toggleHint = 'Requires the Circuit Breaker helper to be installed.';
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {capabilities.map((capability) => (
        <CapabilityCard key={capability.key} capability={capability} />
      ))}

      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          gap: 24,
        }}
      >
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 13, fontWeight: 500, marginBottom: 2 }}>Enable LAN Discovery</div>
          <div style={{ fontSize: 11, color: 'var(--color-text-muted)', lineHeight: 1.5 }}>
            {toggleHint}
          </div>
        </div>
        <div style={{ flexShrink: 0, paddingTop: 2 }}>
          <Toggle
            checked={lanDiscoveryDesired}
            onChange={onToggleLanDiscovery}
            disabled={toggleDisabled}
            ariaLabel="Enable LAN Discovery"
          />
        </div>
      </div>
    </div>
  );
}
