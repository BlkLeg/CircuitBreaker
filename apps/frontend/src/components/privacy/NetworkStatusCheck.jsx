import React, { useState } from 'react';
import { CheckCircle, AlertTriangle, XCircle, HelpCircle } from 'lucide-react';

const CHECK_META = {
  captive_portal: {
    label: 'Captive Portal',
    description: 'Tests whether connectivity probes are intercepted',
  },
  dns_tamper: {
    label: 'DNS Integrity',
    description: 'Verifies DNS answers match known-stable IPs',
  },
  dns_filtering_absent: {
    label: 'DNS Filtering',
    description: 'Checks if known-malware domains are blocked',
  },
};

const STATUS_CONFIG = {
  ok: {
    icon: CheckCircle,
    label: 'OK',
    color: 'var(--color-success, #22c55e)',
    bg: 'rgba(34, 197, 94, 0.1)',
    border: 'rgba(34, 197, 94, 0.25)',
  },
  info: {
    icon: HelpCircle,
    label: 'INFO',
    color: 'var(--color-info, #3b82f6)',
    bg: 'rgba(59, 130, 246, 0.1)',
    border: 'rgba(59, 130, 246, 0.25)',
  },
  warning: {
    icon: AlertTriangle,
    label: 'WARNING',
    color: 'var(--color-warning, #eab308)',
    bg: 'rgba(234, 179, 8, 0.1)',
    border: 'rgba(234, 179, 8, 0.25)',
  },
  critical: {
    icon: XCircle,
    label: 'CRITICAL',
    color: 'var(--color-danger, #ef4444)',
    bg: 'rgba(239, 68, 68, 0.1)',
    border: 'rgba(239, 68, 68, 0.25)',
  },
  unknown: {
    icon: HelpCircle,
    label: 'UNKNOWN',
    color: 'var(--color-text-muted, #6b7280)',
    bg: 'rgba(107, 114, 128, 0.1)',
    border: 'rgba(107, 114, 128, 0.25)',
  },
};

function StatusCard({ check }) {
  const [showDetail, setShowDetail] = useState(false);
  const meta = CHECK_META[check.check_id] || { label: check.check_id, description: '' };
  const config = STATUS_CONFIG[check.status] || STATUS_CONFIG.unknown;
  const Icon = config.icon;

  return (
    <div
      style={{
        flex: 1,
        minWidth: 140,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 10,
        padding: '20px 12px',
        borderRadius: 12,
        background: config.bg,
        border: `1px solid ${config.border}`,
        transition: 'transform 0.15s ease',
      }}
    >
      <div
        style={{ fontSize: 13, fontWeight: 600, textAlign: 'center', color: 'var(--color-text)' }}
      >
        {meta.label}
      </div>
      <div
        style={{
          width: 56,
          height: 56,
          borderRadius: '50%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: config.bg,
          border: `2px solid ${config.color}`,
        }}
      >
        <Icon size={28} color={config.color} />
      </div>
      <div style={{ fontSize: 14, fontWeight: 700, color: config.color, letterSpacing: '0.03em' }}>
        {config.label}
      </div>
      <button
        onClick={() => setShowDetail(!showDetail)}
        style={{
          fontSize: 11,
          color: 'var(--color-primary, #00f5ff)',
          background: 'none',
          border: 'none',
          cursor: 'pointer',
          textDecoration: 'underline',
          padding: 0,
        }}
      >
        {showDetail ? 'Hide info' : 'More info'}
      </button>
      {showDetail && (
        <div
          style={{
            fontSize: 11,
            color: 'var(--color-text-muted)',
            textAlign: 'center',
            lineHeight: 1.4,
            marginTop: -4,
          }}
        >
          {check.evidence || meta.description}
        </div>
      )}
    </div>
  );
}

export default function NetworkStatusCheck({ checks }) {
  if (!checks?.length) return null;

  // Order checks to match mockup: captive_portal, dns_tamper, dns_filtering_absent
  const ordered = ['captive_portal', 'dns_tamper', 'dns_filtering_absent']
    .map((id) => checks.find((c) => c.check_id === id))
    .filter(Boolean);

  return (
    <div className="card privacy-card" style={{ padding: 20 }}>
      <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 16 }}>Network Status Check</div>
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        {ordered.map((check) => (
          <StatusCard key={check.check_id} check={check} />
        ))}
      </div>
    </div>
  );
}
