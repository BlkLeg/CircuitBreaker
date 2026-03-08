import React, { useState, useEffect } from 'react';

export default function ProxmoxDiscoveryModal({ integrationId, onClose, onComplete }) {
  const [phase, setPhase] = useState('starting');
  const [message, setMessage] = useState('Connecting to Proxmox cluster...');
  const [percent, setPercent] = useState(0);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    const run = async () => {
      try {
        const { proxmoxApi } = await import('../../api/client');
        const res = await proxmoxApi.discover(integrationId);
        const data = res.data;
        setResult(data);
        setPhase('done');
        setPercent(100);
        setMessage(
          data.ok
            ? `Imported ${data.nodes_imported} nodes, ${data.vms_imported} VMs, ${data.cts_imported} CTs, ${data.storage_imported || 0} storage`
            : `Discovery completed with errors`
        );
        if (onComplete) onComplete(data);
      } catch (e) {
        setError(e.message || 'Discovery failed');
        setPhase('error');
      }
    };

    run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [integrationId]);

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 9999,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'rgba(0,0,0,0.6)',
        backdropFilter: 'blur(4px)',
      }}
      onClick={(e) => e.target === e.currentTarget && phase !== 'starting' && onClose?.()}
    >
      <div
        style={{
          background: 'var(--color-surface, #1e1e2e)',
          borderRadius: 12,
          padding: '28px 32px',
          minWidth: 420,
          maxWidth: 520,
          boxShadow: '0 20px 60px rgba(0,0,0,0.4)',
          border: '1px solid var(--color-border, rgba(255,255,255,0.08))',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 20 }}>
          <svg
            width="22"
            height="22"
            viewBox="0 0 24 24"
            fill="none"
            stroke="var(--color-primary, #fe8019)"
            strokeWidth="2"
          >
            <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
          </svg>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 600 }}>
            {phase === 'done'
              ? 'Discovery Complete'
              : phase === 'error'
                ? 'Discovery Failed'
                : 'Discovering Proxmox Cluster'}
          </h3>
        </div>

        <p style={{ fontSize: 13, color: 'var(--color-text-muted)', margin: '0 0 16px' }}>
          {message}
        </p>

        {/* Progress bar */}
        <div
          style={{
            height: 6,
            borderRadius: 3,
            background: 'var(--color-bg-elevated, rgba(255,255,255,0.06))',
            overflow: 'hidden',
            marginBottom: 16,
          }}
        >
          <div
            style={{
              height: '100%',
              borderRadius: 3,
              width: phase === 'starting' ? '40%' : `${percent}%`,
              background: error
                ? '#ef4444'
                : 'linear-gradient(90deg, var(--color-primary, #fe8019), #fabd2f)',
              transition: 'width 0.5s ease',
              animation: phase === 'starting' ? 'pulse 1.5s ease-in-out infinite' : 'none',
            }}
          />
        </div>

        {/* Results summary */}
        {result && (
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(4, 1fr)',
              gap: 10,
              marginBottom: 16,
            }}
          >
            {[
              { label: 'Nodes', value: result.nodes_imported, color: '#22c55e' },
              { label: 'VMs', value: result.vms_imported, color: '#3b82f6' },
              { label: 'Containers', value: result.cts_imported, color: '#a855f7' },
              { label: 'Storage', value: result.storage_imported || 0, color: '#f59e0b' },
            ].map(({ label, value, color }) => (
              <div
                key={label}
                style={{
                  textAlign: 'center',
                  padding: '10px 8px',
                  borderRadius: 8,
                  background: 'var(--color-bg-elevated, rgba(255,255,255,0.04))',
                }}
              >
                <div style={{ fontSize: 22, fontWeight: 700, color }}>{value}</div>
                <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 2 }}>
                  {label}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Errors */}
        {(error || result?.errors?.length > 0) && (
          <div
            style={{
              fontSize: 12,
              color: '#ef4444',
              background: 'rgba(239,68,68,0.08)',
              padding: '8px 12px',
              borderRadius: 6,
              maxHeight: 100,
              overflowY: 'auto',
              marginBottom: 16,
            }}
          >
            {error || result.errors.join('\n')}
          </div>
        )}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          {phase !== 'starting' && (
            <button
              className="btn btn-sm"
              onClick={onClose}
              style={{
                padding: '6px 18px',
                borderRadius: 6,
                fontSize: 13,
                fontWeight: 500,
              }}
            >
              Close
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
