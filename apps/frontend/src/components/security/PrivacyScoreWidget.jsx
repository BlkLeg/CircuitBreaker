import React, { useEffect, useState } from 'react';
import { Shield, ShieldAlert, ShieldCheck } from 'lucide-react';
import { windscribeApi } from '../../api/client';

export default function PrivacyScoreWidget() {
  const [data, setData] = useState(null);

  useEffect(() => {
    windscribeApi
      .getNetworkPrivacyScore()
      .then((res) => setData(res.data))
      .catch(console.error);
  }, []);

  if (!data) return null;

  const score = data.score;
  const color =
    score > 80
      ? 'var(--color-success, #22c55e)'
      : score > 50
        ? 'var(--color-warning, #eab308)'
        : 'var(--color-danger, #ef4444)';
  const Icon = score > 80 ? ShieldCheck : score > 50 ? Shield : ShieldAlert;

  return (
    <div
      style={{
        position: 'absolute',
        top: 16,
        right: 16,
        background: 'var(--color-surface)',
        border: '1px solid var(--color-border)',
        borderRadius: 12,
        padding: '12px 16px',
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        zIndex: 100,
        boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)',
      }}
    >
      <div
        style={{
          background: `${color}20`,
          color: color,
          padding: 8,
          borderRadius: '50%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Icon size={24} />
      </div>
      <div>
        <div
          style={{
            fontSize: 12,
            color: 'var(--color-text-muted)',
            fontWeight: 500,
            textTransform: 'uppercase',
            letterSpacing: '0.05em',
          }}
        >
          Network Privacy
        </div>
        <div style={{ fontSize: 24, fontWeight: 700, color: 'var(--color-text)', lineHeight: 1 }}>
          {score}
          <span style={{ fontSize: 14, color: 'var(--color-text-muted)', fontWeight: 500 }}>
            /100
          </span>
        </div>
      </div>
    </div>
  );
}
