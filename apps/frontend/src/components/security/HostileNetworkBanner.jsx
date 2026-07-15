import React, { useEffect, useState } from 'react';
import { AlertTriangle, ShieldAlert } from 'lucide-react';
import { windscribeApi } from '../../api/client';

const SEVERITY_STYLES = {
  warning: {
    background: 'rgba(234, 179, 8, 0.12)',
    border: '1px solid var(--color-warning, #eab308)',
    color: 'var(--color-warning, #eab308)',
  },
  critical: {
    background: 'rgba(239, 68, 68, 0.12)',
    border: '1px solid var(--color-danger, #ef4444)',
    color: 'var(--color-danger, #ef4444)',
  },
};

/**
 * Renders only on real hostile-network alerts (status warning/critical).
 * Safe/unknown/disabled states render nothing — no more always-on banner.
 */
export default function HostileNetworkBanner() {
  const [alertState, setAlertState] = useState(null);

  useEffect(() => {
    windscribeApi
      .getNetworkThreatAlerts()
      .then((res) => setAlertState(res.data))
      .catch((err) => console.error('Threat alerts fetch failed:', err));
  }, []);

  if (!alertState || !['warning', 'critical'].includes(alertState.status)) return null;

  const severityStyle = SEVERITY_STYLES[alertState.status];
  const Icon = alertState.status === 'critical' ? ShieldAlert : AlertTriangle;
  const detail = alertState.alerts?.[0]?.detail;

  return (
    <div
      style={{
        position: 'absolute',
        top: 16,
        left: '50%',
        transform: 'translateX(-50%)',
        borderRadius: 8,
        padding: '8px 16px',
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        zIndex: 100,
        fontWeight: 500,
        backdropFilter: 'blur(4px)',
        ...severityStyle,
      }}
    >
      <Icon size={18} />
      {alertState.status === 'critical' ? 'Hostile network detected' : 'Network anomaly detected'}
      {detail && <span style={{ fontWeight: 400, fontSize: 13, opacity: 0.9 }}>— {detail}</span>}
    </div>
  );
}
