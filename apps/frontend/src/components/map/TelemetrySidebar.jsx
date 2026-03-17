import React, { useEffect, useLayoutEffect, useState, useRef } from 'react';
import PropTypes from 'prop-types';
import {
  X,
  HardDrive,
  Network,
  Clock,
  Server,
  Container,
  CheckCircle,
  AlertCircle,
} from 'lucide-react';
import { telemetryApi, proxmoxApi } from '../../api/client';

function BarMeter({ label, value, max, color, unit }) {
  const pct = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0;
  return (
    <div style={{ marginBottom: 6 }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          fontSize: 11,
          marginBottom: 2,
          color: 'var(--color-text-secondary)',
        }}
      >
        <span>{label}</span>
        <span style={{ fontFamily: 'monospace' }}>
          {pct}%{unit ? ` (${value}${unit}/${max}${unit})` : ''}
        </span>
      </div>
      <div style={{ width: '100%', height: 5, borderRadius: 3, background: 'var(--color-border)' }}>
        <div
          style={{
            width: `${pct}%`,
            height: '100%',
            borderRadius: 3,
            background: color || '#3b82f6',
            transition: 'width 0.3s',
          }}
        />
      </div>
    </div>
  );
}
BarMeter.propTypes = {
  label: PropTypes.string,
  value: PropTypes.number,
  max: PropTypes.number,
  color: PropTypes.string,
  unit: PropTypes.string,
};

function formatUptime(seconds) {
  if (!seconds) return '—';
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function formatRate(bytes) {
  if (!bytes && bytes !== 0) return '—';
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB/s`;
  if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)} MB/s`;
  if (bytes >= 1e3) return `${(bytes / 1e3).toFixed(0)} KB/s`;
  return `${bytes} B/s`;
}

function meterColor(pct) {
  if (pct >= 90) return '#ef4444';
  if (pct >= 70) return '#f59e0b';
  return '#22c55e';
}

const HEALTHY_STATUSES = new Set(['active', 'running', 'online']);
const HEALTHY_TELEMETRY = new Set(['ok', 'healthy']);

function isHealthyStatus(data) {
  const status = String(data?.status || '')
    .trim()
    .toLowerCase();
  const telemetry = String(data?.telemetry_status || '')
    .trim()
    .toLowerCase();
  return HEALTHY_STATUSES.has(status) || HEALTHY_TELEMETRY.has(telemetry);
}

const NODE_STYLES = new Map([
  ['cluster', { background: '#7c3aed', borderColor: '#5b21b6', glowColor: '#a78bfa' }], // violet
  ['hardware', { background: '#4a7fa5', borderColor: '#2c5f7a', glowColor: '#4a7fa5' }], // steel blue
  ['compute', { background: '#3a7d44', borderColor: '#1f5c2c', glowColor: '#3a7d44' }], // green
  ['service', { background: '#c2601e', borderColor: '#8f4012', glowColor: '#e07030' }], // orange
  ['storage', { background: '#7b4fa0', borderColor: '#5a3278', glowColor: '#7b4fa0' }], // purple
  ['network', { background: '#0e8a8a', borderColor: '#0a6060', glowColor: '#0eb8b8' }], // cyan
  ['misc', { background: '#4a5568', borderColor: '#2d3748', glowColor: '#6b7a96' }], // gray
  ['external', { background: '#2196f3', borderColor: '#1565c0', glowColor: '#64b5f6' }], // sky blue
  ['docker_network', { background: '#0b6e8e', borderColor: '#086080', glowColor: '#1cb8d8' }], // docker teal
  ['docker_container', { background: '#1e6ba8', borderColor: '#164e80', glowColor: '#2d8ae0' }], // docker blue
]);

const NODE_TYPE_LABELS = new Map([
  ['cluster', 'Cluster'],
  ['hardware', 'Hardware'],
  ['compute', 'Compute'],
  ['service', 'Service'],
  ['storage', 'Storage'],
  ['network', 'Network'],
  ['misc', 'Misc'],
  ['external', 'External'],
  ['docker_network', 'Docker Net'],
  ['docker_container', 'Container'],
]);

export default function TelemetrySidebar({ node, position, onClose, onBoundsChange }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [clusterOverview, setClusterOverview] = useState(null);
  const [adjustedPos, setAdjustedPos] = useState({ x: position?.x ?? 200, y: position?.y ?? 100 });
  const sidebarRef = useRef(null);

  const integrationId = node?.data?.integration_config_id ?? null;

  const typeMap = {
    hardware: 'hardware',
    compute: 'compute_unit',
    compute_unit: 'compute_unit',
    virtual_machine: 'compute_unit',
    docker_container: 'compute_unit',
    storage: 'storage',
  };
  const entityType = typeMap[node?.originalType] || null;
  const entityId = node?._refId;

  useLayoutEffect(() => {
    if (sidebarRef.current && position) {
      const rect = sidebarRef.current.getBoundingClientRect();
      const margin = 10;
      let x = position.x;
      let y = position.y;

      // Adjust for right edge
      if (x + rect.width + margin > window.innerWidth) {
        x = window.innerWidth - rect.width - margin;
      }
      // Adjust for bottom edge
      if (y + rect.height + margin > window.innerHeight) {
        y = window.innerHeight - rect.height - margin;
      }
      // Adjust for left edge
      if (x < margin) {
        x = margin;
      }
      // Adjust for top edge
      if (y < margin) {
        y = margin;
      }

      setAdjustedPos({ x, y });
    }
  }, [position, data]);

  // Report bounds so the context menu can shift away and avoid overlapping this hover box
  useLayoutEffect(() => {
    if (!onBoundsChange) return;
    const el = sidebarRef.current;
    if (!el) return;
    const rafId = requestAnimationFrame(() => {
      const r = el.getBoundingClientRect();
      onBoundsChange({
        left: r.left,
        top: r.top,
        right: r.right,
        bottom: r.bottom,
        width: r.width,
        height: r.height,
      });
    });
    return () => cancelAnimationFrame(rafId);
  }, [adjustedPos, data, onBoundsChange]);

  useEffect(() => {
    return () => onBoundsChange?.(null);
  }, [onBoundsChange]);

  useEffect(() => {
    if (!entityType || !entityId) return;
    let cancelled = false;
    setLoading(true);
    telemetryApi
      .getEntity(entityType, entityId)
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch(() => {
        if (!cancelled) setData(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [entityType, entityId]);

  useEffect(() => {
    if (!integrationId) {
      setClusterOverview(null);
      return;
    }
    let cancelled = false;
    proxmoxApi
      .clusterOverview(integrationId)
      .then((res) => {
        if (!cancelled) setClusterOverview(res.data);
      })
      .catch(() => {
        if (!cancelled) setClusterOverview(null);
      });
    return () => {
      cancelled = true;
    };
  }, [integrationId]);

  if (!node) return null;

  const cpuPct = data?.cpu_pct != null ? Math.round(data.cpu_pct * 100) : null;
  const memUsed =
    data?.mem_used_gb ?? (data?.mem_used != null ? +(data.mem_used / 1073741824).toFixed(1) : null);
  const memTotal =
    data?.mem_total_gb ??
    (data?.mem_total != null ? +(data.mem_total / 1073741824).toFixed(1) : null);
  const diskUsed =
    data?.disk_used_gb ??
    (data?.rootfs_used != null ? +(data.rootfs_used / 1073741824).toFixed(1) : null);
  const diskTotal =
    data?.disk_total_gb ??
    (data?.rootfs_total != null ? +(data.rootfs_total / 1073741824).toFixed(1) : null);

  return (
    <div
      ref={sidebarRef}
      style={{
        position: 'absolute',
        left: adjustedPos.x,
        top: adjustedPos.y,
        zIndex: 9999,
        width: 260,
        background: 'var(--color-surface)',
        border: '1px solid var(--color-border)',
        borderRadius: 10,
        boxShadow: '0 8px 32px rgba(0,0,0,0.35)',
        padding: 14,
        fontFamily: 'var(--font-sans, sans-serif)',
        color: 'var(--color-text)',
        pointerEvents: 'auto',
        opacity:
          adjustedPos.x === position?.x && adjustedPos.y === position?.y && !sidebarRef.current
            ? 0
            : 1,
      }}
      onMouseLeave={onClose}
    >
      {/* Header with Basic Information */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          marginBottom: 8,
        }}
      >
        <div style={{ flex: 1, minWidth: 0, paddingRight: 8 }}>
          <div
            style={{
              fontWeight: 600,
              fontSize: 14,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {node?.data?.label || data?.name || '…'}
          </div>
          <div
            style={{
              color: 'var(--color-text-muted)',
              fontSize: 11,
              marginTop: 4,
              display: 'flex',
              flexWrap: 'wrap',
              gap: 6,
              alignItems: 'center',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <span
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: '50%',
                  background:
                    NODE_STYLES.get(node?.originalType)?.glowColor || 'var(--color-text-muted)',
                  boxShadow: `0 0 6px ${NODE_STYLES.get(node?.originalType)?.glowColor || 'transparent'}`,
                }}
              />
              <span>{NODE_TYPE_LABELS.get(node?.originalType) || node?.originalType}</span>
            </div>
            {node?.originalType === 'hardware' && node?._hwRole && (
              <>
                <span style={{ color: 'var(--color-border)' }}>|</span>
                <span style={{ color: 'var(--color-text)' }}>{node._hwRole}</span>
              </>
            )}
            {/* IP / CIDR */}
            {(node?.data?.ip_address || node?.data?.cidr) && (
              <>
                <span style={{ color: 'var(--color-border)' }}>|</span>
                <span style={{ fontFamily: 'monospace', color: 'var(--color-primary)' }}>
                  {node.data.ip_address || node.data.cidr}
                </span>
              </>
            )}
            {/* Docker image */}
            {node?.data?.docker_image && (
              <>
                <span style={{ color: 'var(--color-border)' }}>|</span>
                <span
                  style={{
                    fontFamily: 'monospace',
                    color: 'var(--color-text)',
                    maxWidth: 150,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                  title={node.data.docker_image}
                >
                  {node.data.docker_image.split('/').pop()}
                </span>
              </>
            )}
          </div>
          {/* Tags */}
          {node?._tags?.length > 0 && (
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 6 }}>
              {node._tags.map((t) => (
                <span
                  key={t}
                  style={{
                    background: 'var(--color-surface-hover)',
                    color: 'var(--color-text-secondary)',
                    borderRadius: 3,
                    padding: '1px 5px',
                    fontSize: 10,
                    border: '1px solid var(--color-border)',
                  }}
                >
                  {t}
                </span>
              ))}
            </div>
          )}
        </div>
        <button
          onClick={onClose}
          style={{
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            color: 'var(--color-text-muted)',
            padding: 4,
            marginTop: -2,
            marginRight: -4,
          }}
        >
          <X size={14} />
        </button>
      </div>

      <hr
        style={{ border: 'none', borderTop: '1px solid var(--color-border)', margin: '0 0 10px 0' }}
      />

      {loading && (
        <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>Loading telemetry…</div>
      )}

      {!loading && data && entityType === 'hardware' && (
        <>
          {/* Status */}
          <div style={{ marginBottom: 8, display: 'flex', gap: 6, alignItems: 'center' }}>
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: '50%',
                background: isHealthyStatus(data) ? '#22c55e' : '#ef4444',
                display: 'inline-block',
              }}
            />
            <span style={{ fontSize: 11, color: 'var(--color-text-secondary)' }}>
              {data.telemetry_status || data.status || 'unknown'}
            </span>
            {data.uptime_s != null && (
              <span style={{ fontSize: 11, color: 'var(--color-text-muted)', marginLeft: 'auto' }}>
                <Clock size={11} style={{ verticalAlign: -1, marginRight: 2 }} />
                {formatUptime(data.uptime_s)}
              </span>
            )}
          </div>

          {cpuPct != null && (
            <BarMeter label="CPU" value={cpuPct} max={100} color={meterColor(cpuPct)} />
          )}
          {memUsed != null && memTotal != null && (
            <BarMeter
              label={`Memory (${memUsed}/${memTotal} GB)`}
              value={memUsed}
              max={memTotal}
              color={meterColor((memUsed / memTotal) * 100)}
            />
          )}
          {diskUsed != null && diskTotal != null && (
            <BarMeter
              label={`Disk (${diskUsed}/${diskTotal} GB)`}
              value={diskUsed}
              max={diskTotal}
              color={meterColor((diskUsed / diskTotal) * 100)}
            />
          )}

          {/* Network */}
          {(data.net_rx != null || data.net_tx != null) && (
            <div
              style={{
                display: 'flex',
                gap: 10,
                fontSize: 11,
                color: 'var(--color-text-secondary)',
                marginBottom: 6,
              }}
            >
              <Network size={12} style={{ flexShrink: 0, marginTop: 1 }} />
              <span>↓ {formatRate(data.net_rx)}</span>
              <span>↑ {formatRate(data.net_tx)}</span>
            </div>
          )}

          {/* Children */}
          {(data.child_vms || data.child_cts) && (
            <div
              style={{ marginTop: 6, padding: '6px 0', borderTop: '1px solid var(--color-border)' }}
            >
              <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 4 }}>
                Guests
              </div>
              {data.child_vms && (
                <div
                  style={{
                    display: 'flex',
                    gap: 6,
                    alignItems: 'center',
                    fontSize: 11,
                    marginBottom: 2,
                  }}
                >
                  <Server size={11} />
                  <span>{data.child_vms.running} VMs running</span>
                  {data.child_vms.stopped > 0 && (
                    <span style={{ color: 'var(--color-text-muted)' }}>
                      ({data.child_vms.stopped} stopped)
                    </span>
                  )}
                </div>
              )}
              {data.child_cts && (
                <div style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 11 }}>
                  <Container size={11} />
                  <span>{data.child_cts.running} CTs running</span>
                  {data.child_cts.stopped > 0 && (
                    <span style={{ color: 'var(--color-text-muted)' }}>
                      ({data.child_cts.stopped} stopped)
                    </span>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Storage summary */}
          {data.storage_summary?.length > 0 && (
            <div
              style={{ marginTop: 6, padding: '6px 0', borderTop: '1px solid var(--color-border)' }}
            >
              <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 4 }}>
                Storage
              </div>
              {data.storage_summary.map((s, i) => {
                const sPct = s.capacity_gb > 0 ? Math.round((s.used_gb / s.capacity_gb) * 100) : 0;
                return (
                  <div key={i} style={{ marginBottom: 4 }}>
                    <div
                      style={{
                        fontSize: 10,
                        color: 'var(--color-text-secondary)',
                        marginBottom: 1,
                      }}
                    >
                      {s.name}
                    </div>
                    <div
                      style={{
                        width: '100%',
                        height: 4,
                        borderRadius: 2,
                        background: 'var(--color-border)',
                      }}
                    >
                      <div
                        style={{
                          width: `${sPct}%`,
                          height: '100%',
                          borderRadius: 2,
                          background: meterColor(sPct),
                        }}
                      />
                    </div>
                    <div
                      style={{
                        fontSize: 9,
                        color: 'var(--color-text-muted)',
                        fontFamily: 'monospace',
                      }}
                    >
                      {s.used_gb ?? 0}/{s.capacity_gb ?? 0} GB ({sPct}%)
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </>
      )}

      {!loading && data && entityType === 'compute_unit' && (
        <>
          <div style={{ marginBottom: 6, display: 'flex', gap: 6, alignItems: 'center' }}>
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: '50%',
                background: isHealthyStatus(data) ? '#22c55e' : '#ef4444',
                display: 'inline-block',
              }}
            />
            <span style={{ fontSize: 11, color: 'var(--color-text-secondary)' }}>
              {data.status || 'unknown'}
            </span>
            {data.proxmox_vmid && (
              <span
                style={{
                  fontSize: 10,
                  color: 'var(--color-text-muted)',
                  marginLeft: 'auto',
                  fontFamily: 'monospace',
                }}
              >
                {data.proxmox_type?.toUpperCase()} #{data.proxmox_vmid}
              </span>
            )}
          </div>

          {cpuPct != null && (
            <BarMeter label="CPU" value={cpuPct} max={100} color={meterColor(cpuPct)} />
          )}
          {memUsed != null && memTotal != null && (
            <BarMeter
              label={`Memory (${memUsed}/${memTotal} GB)`}
              value={memUsed}
              max={memTotal}
              color={meterColor((memUsed / memTotal) * 100)}
            />
          )}
          {diskUsed != null && diskTotal != null && (
            <BarMeter
              label={`Disk (${diskUsed}/${diskTotal} GB)`}
              value={diskUsed}
              max={diskTotal}
              color={meterColor((diskUsed / diskTotal) * 100)}
            />
          )}
          {(data.netin != null || data.netout != null) && (
            <div
              style={{
                display: 'flex',
                gap: 10,
                fontSize: 11,
                color: 'var(--color-text-secondary)',
              }}
            >
              <Network size={12} style={{ flexShrink: 0, marginTop: 1 }} />
              <span>↓ {formatRate(data.netin)}</span>
              <span>↑ {formatRate(data.netout)}</span>
            </div>
          )}
        </>
      )}

      {clusterOverview && (
        <div
          style={{
            marginTop: 10,
            paddingTop: 10,
            borderTop: '1px solid var(--color-border)',
          }}
        >
          <div
            style={{
              fontSize: 11,
              fontWeight: 600,
              color: 'var(--color-text-muted)',
              marginBottom: 6,
              textTransform: 'uppercase',
              letterSpacing: '0.05em',
            }}
          >
            Proxmox cluster
          </div>
          <div style={{ fontSize: 11, color: 'var(--color-text)', marginBottom: 4 }}>
            {clusterOverview.cluster?.name || '—'}
          </div>
          <div
            style={{
              display: 'flex',
              flexWrap: 'wrap',
              gap: 8,
              alignItems: 'center',
              fontSize: 11,
              color: 'var(--color-text-secondary)',
              marginBottom: 6,
            }}
          >
            <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              {clusterOverview.cluster?.quorum ? (
                <CheckCircle size={12} style={{ color: '#22c55e' }} />
              ) : (
                <AlertCircle size={12} style={{ color: '#ef4444' }} />
              )}
              Quorum {clusterOverview.cluster?.quorum ? 'OK' : 'Fail'}
            </span>
            <span>
              Nodes {clusterOverview.cluster?.nodes_online ?? 0} /{' '}
              {clusterOverview.cluster?.nodes_total ?? 0}
            </span>
            <span>
              Guests {clusterOverview.cluster?.vms ?? 0} VM / {clusterOverview.cluster?.lxcs ?? 0}{' '}
              LXC
            </span>
            {clusterOverview.cluster?.uptime && (
              <span>
                <Clock size={11} style={{ verticalAlign: -1, marginRight: 2 }} />
                {clusterOverview.cluster.uptime}
              </span>
            )}
          </div>
          {clusterOverview.problems?.length > 0 && (
            <div style={{ marginBottom: 6 }}>
              <div
                style={{
                  fontSize: 10,
                  color: 'var(--color-text-muted)',
                  marginBottom: 3,
                  fontWeight: 600,
                }}
              >
                Problems
              </div>
              {clusterOverview.problems.slice(0, 3).map((p, i) => (
                <div
                  key={i}
                  style={{
                    fontSize: 10,
                    color: 'var(--color-text-secondary)',
                    marginBottom: 2,
                    paddingLeft: 6,
                    borderLeft: `2px solid ${p.severity === 'high' ? '#ef4444' : p.severity === 'warning' ? '#f59e0b' : 'var(--color-border)'}`,
                  }}
                >
                  {p.host}: {p.problem}
                </div>
              ))}
            </div>
          )}
          {clusterOverview.storage?.length > 0 && (
            <div>
              <div
                style={{
                  fontSize: 10,
                  color: 'var(--color-text-muted)',
                  marginBottom: 3,
                  fontWeight: 600,
                }}
              >
                Storage
              </div>
              {clusterOverview.storage.slice(0, 4).map((s, i) => {
                const total = s.total_gb ?? 0;
                const used = s.used_gb ?? 0;
                const pct = total > 0 ? Math.round((used / total) * 100) : 0;
                return (
                  <div key={i} style={{ marginBottom: 3 }}>
                    <div
                      style={{
                        fontSize: 10,
                        color: 'var(--color-text-secondary)',
                        marginBottom: 1,
                      }}
                    >
                      {s.name}
                    </div>
                    <div
                      style={{
                        width: '100%',
                        height: 4,
                        borderRadius: 2,
                        background: 'var(--color-border)',
                      }}
                    >
                      <div
                        style={{
                          width: `${pct}%`,
                          height: '100%',
                          borderRadius: 2,
                          background: meterColor(pct),
                        }}
                      />
                    </div>
                    <div
                      style={{
                        fontSize: 9,
                        color: 'var(--color-text-muted)',
                        fontFamily: 'monospace',
                      }}
                    >
                      {used.toFixed(0)} / {total.toFixed(0)} GB ({pct}%)
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {!loading && data && entityType === 'storage' && (
        <>
          <div style={{ marginBottom: 6, fontSize: 11, color: 'var(--color-text-secondary)' }}>
            {data.kind} / {data.protocol}
          </div>
          {data.capacity_gb != null && data.used_gb != null && (
            <BarMeter
              label={`Capacity (${data.used_gb}/${data.capacity_gb} GB)`}
              value={data.used_gb}
              max={data.capacity_gb}
              color={meterColor(data.capacity_gb > 0 ? (data.used_gb / data.capacity_gb) * 100 : 0)}
            />
          )}
          {data.parent_node && (
            <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 4 }}>
              <HardDrive size={11} style={{ verticalAlign: -1, marginRight: 3 }} />
              {data.parent_node}
            </div>
          )}
        </>
      )}

      {!loading && !data && (
        <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
          {/* Storage summary (hardware) */}
          {node?.data?.storage_summary &&
            (() => {
              const s = node.data.storage_summary;
              const tb =
                s.total_gb >= 1024 ? `${(s.total_gb / 1024).toFixed(1)}TB` : `${s.total_gb}GB`;
              const types = s.types?.join(', ') || '';
              const usedPct =
                s.used_gb != null && s.total_gb > 0
                  ? `${Math.round((s.used_gb / s.total_gb) * 100)}% used`
                  : null;
              const parts = [usedPct, types].filter(Boolean).join(', ');
              return (
                <div
                  style={{
                    fontSize: 11,
                    color: 'var(--color-text-muted)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 4,
                  }}
                >
                  <HardDrive size={12} />
                  <span>
                    {tb} total{parts ? ` (${parts})` : ''}
                  </span>
                  {s.primary_pool && <span>· {s.primary_pool}</span>}
                </div>
              );
            })()}

          {/* Storage allocated (compute) */}
          {node?.data?.storage_allocated?.disk_gb && (
            <div
              style={{
                fontSize: 11,
                color: 'var(--color-text-muted)',
                display: 'flex',
                alignItems: 'center',
                gap: 4,
              }}
            >
              <HardDrive size={12} />
              <span>{node.data.storage_allocated.disk_gb} GB disk</span>
              {node.data.storage_allocated.storage_pools?.length > 0 && (
                <span>· {node.data.storage_allocated.storage_pools.join(', ')}</span>
              )}
            </div>
          )}

          {/* Capacity (storage nodes) */}
          {node?.data?.capacity_gb && (
            <div
              style={{
                fontSize: 11,
                color: 'var(--color-text-muted)',
                display: 'flex',
                alignItems: 'center',
                gap: 4,
              }}
            >
              <HardDrive size={12} />
              <span>
                {node.data.capacity_gb >= 1024
                  ? `${(node.data.capacity_gb / 1024).toFixed(1)} TB`
                  : `${node.data.capacity_gb} GB`}{' '}
                capacity
              </span>
              {node.data.used_gb != null && node.data.capacity_gb > 0 && (
                <span>({Math.round((node.data.used_gb / node.data.capacity_gb) * 100)}% used)</span>
              )}
            </div>
          )}
        </div>
      )}

      {/* Renders safely when data is null, but only if it's meant to have telemetry */}

      {!loading && !data && (
        <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
          {/* Storage summary (hardware) */}
          {node?.data?.storage_summary &&
            (() => {
              const s = node.data.storage_summary;
              const tb =
                s.total_gb >= 1024 ? `${(s.total_gb / 1024).toFixed(1)}TB` : `${s.total_gb}GB`;
              const types = s.types?.join(', ') || '';
              const usedPct =
                s.used_gb != null && s.total_gb > 0
                  ? `${Math.round((s.used_gb / s.total_gb) * 100)}% used`
                  : null;
              const parts = [usedPct, types].filter(Boolean).join(', ');
              return (
                <div
                  style={{
                    fontSize: 11,
                    color: 'var(--color-text-muted)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 4,
                  }}
                >
                  <HardDrive size={12} />
                  <span>
                    {tb} total{parts ? ` (${parts})` : ''}
                  </span>
                  {s.primary_pool && <span>· {s.primary_pool}</span>}
                </div>
              );
            })()}

          {/* Storage allocated (compute) */}
          {node?.data?.storage_allocated?.disk_gb && (
            <div
              style={{
                fontSize: 11,
                color: 'var(--color-text-muted)',
                display: 'flex',
                alignItems: 'center',
                gap: 4,
              }}
            >
              <HardDrive size={12} />
              <span>{node.data.storage_allocated.disk_gb} GB disk</span>
              {node.data.storage_allocated.storage_pools?.length > 0 && (
                <span>· {node.data.storage_allocated.storage_pools.join(', ')}</span>
              )}
            </div>
          )}

          {/* Capacity (storage nodes) */}
          {node?.data?.capacity_gb && (
            <div
              style={{
                fontSize: 11,
                color: 'var(--color-text-muted)',
                display: 'flex',
                alignItems: 'center',
                gap: 4,
              }}
            >
              <HardDrive size={12} />
              <span>
                {node.data.capacity_gb >= 1024
                  ? `${(node.data.capacity_gb / 1024).toFixed(1)} TB`
                  : `${node.data.capacity_gb} GB`}{' '}
                capacity
              </span>
              {node.data.used_gb != null && node.data.capacity_gb > 0 && (
                <span>({Math.round((node.data.used_gb / node.data.capacity_gb) * 100)}% used)</span>
              )}
            </div>
          )}
        </div>
      )}

      {/* Renders safely when data is null, but only if it's meant to have telemetry */}
      {!loading && !data && entityType && (
        <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
          No telemetry data available.
        </div>
      )}
    </div>
  );
}

TelemetrySidebar.propTypes = {
  node: PropTypes.object,
  position: PropTypes.shape({ x: PropTypes.number, y: PropTypes.number }),
  onClose: PropTypes.func.isRequired,
  onBoundsChange: PropTypes.func,
};
