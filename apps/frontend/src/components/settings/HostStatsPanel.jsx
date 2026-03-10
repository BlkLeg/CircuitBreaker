import React, { useEffect, useState } from 'react';
import { systemApi } from '../../api/client';

export default function HostStatsPanel() {
  const [stats, setStats] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let _mounted = true;
    const fetchStats = async () => {
      try {
        const res = await systemApi.getStats();
        if (_mounted) setStats(res.data);
      } catch (err) {
        if (_mounted) setError(err.message);
      }
    };
    fetchStats();
    const interval = setInterval(fetchStats, 5000);
    return () => {
      _mounted = false;
      clearInterval(interval);
    };
  }, []);

  if (error)
    return (
      <div style={{ color: 'var(--color-danger)', fontSize: 13 }}>Failed to load host stats</div>
    );
  if (!stats)
    return (
      <div style={{ color: 'var(--color-text-muted)', fontSize: 13 }}>
        Loading host statistics...
      </div>
    );

  const memPct = ((stats.mem.used / stats.mem.total) * 100).toFixed(1);
  const diskPct = stats.disk.percent.toFixed(1);
  const netInfo = stats.net
    ? `RX: ${(stats.net.bytes_recv / 1024 / 1024 / 1024).toFixed(2)} GB | TX: ${(stats.net.bytes_sent / 1024 / 1024 / 1024).toFixed(2)} GB`
    : 'N/A';

  const cardStyle = {
    padding: '12px 16px',
    borderRadius: 8,
    background: 'var(--color-background)',
    border: '1px solid var(--color-border)',
  };

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
      <div style={cardStyle}>
        <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 4 }}>
          CPU Usage
        </div>
        <div style={{ fontSize: 20, fontWeight: 600 }}>{stats.cpu_pct.toFixed(1)}%</div>
      </div>
      <div style={cardStyle}>
        <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 4 }}>
          Memory Usage
        </div>
        <div style={{ fontSize: 20, fontWeight: 600 }}>{memPct}%</div>
        <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 2 }}>
          {(stats.mem.used / 1024 / 1024 / 1024).toFixed(1)} GB /{' '}
          {(stats.mem.total / 1024 / 1024 / 1024).toFixed(1)} GB
        </div>
      </div>
      <div style={cardStyle}>
        <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 4 }}>
          Disk Usage
        </div>
        <div style={{ fontSize: 20, fontWeight: 600 }}>{diskPct}%</div>
        <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 2 }}>
          {(stats.disk.used / 1024 / 1024 / 1024).toFixed(1)} GB /{' '}
          {(stats.disk.total / 1024 / 1024 / 1024).toFixed(1)} GB
        </div>
      </div>
      <div style={cardStyle}>
        <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 4 }}>
          Network I/O
        </div>
        <div style={{ fontSize: 14, fontWeight: 600, marginTop: 4 }}>{netInfo}</div>
      </div>
    </div>
  );
}
