import React, { useEffect, useState } from 'react';
import { AlertTriangle } from 'lucide-react';
import { windscribeApi } from '../../api/client';

export default function HostileNetworkBanner() {
  const [alerts, setAlerts] = useState(null);

  useEffect(() => {
    windscribeApi
      .getNetworkThreatAlerts()
      .then((res) => setAlerts(res.data))
      .catch(console.error);
  }, []);

  if (!alerts || Object.keys(alerts).length === 0) return null;

  return (
    <div
      style={{
        position: 'absolute',
        top: 16,
        left: '50%',
        transform: 'translateX(-50%)',
        background: 'rgba(239, 68, 68, 0.1)',
        border: '1px solid var(--color-danger, #ef4444)',
        color: 'var(--color-danger, #ef4444)',
        borderRadius: 8,
        padding: '8px 16px',
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        zIndex: 100,
        fontWeight: 500,
        backdropFilter: 'blur(4px)',
      }}
    >
      <AlertTriangle size={18} />
      Hostile Network Detected: Active threats in environment
    </div>
  );
}
