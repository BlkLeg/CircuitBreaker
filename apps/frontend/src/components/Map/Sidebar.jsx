import React, { useEffect, useMemo, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import DOMPurify from 'dompurify';
import {
  X,
  ExternalLink,
  Link2,
  Activity,
  Info,
  FileText,
  Radio,
  ChevronDown,
  ChevronRight,
} from 'lucide-react';
import { AnimatePresence, motion } from 'framer-motion';
import { telemetryApi, docsApi, servicesApi } from '../../api/client';

function formatSpeedLabel(mbps) {
  const value = Number(mbps) || 0;
  if (value >= 1000) {
    return `${(value / 1000).toFixed(1).replace(/\.0$/, '')} Gbps`;
  }
  return `${Math.round(value)} Mbps`;
}

function SectionTitle({ icon: Icon, title }) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        fontSize: 12,
        color: 'var(--color-text-muted)',
        marginBottom: 6,
      }}
    >
      <Icon size={14} />
      <span>{title}</span>
    </div>
  );
}

SectionTitle.propTypes = {
  icon: PropTypes.elementType.isRequired,
  title: PropTypes.string.isRequired,
};

function DocRow({ doc, expanded, onToggle }) {
  const [bodyHtml, setBodyHtml] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!expanded || bodyHtml != null) return;
    let cancelled = false;
    setLoading(true);
    docsApi
      .get(doc.id)
      .then((res) => {
        if (!cancelled) setBodyHtml(res.data?.body_html ?? res.data?.body_md ?? '');
      })
      .catch(() => {
        if (!cancelled) setBodyHtml('');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [doc.id, expanded, bodyHtml]);

  const title = doc.title || 'Untitled';
  const truncated = title.length > 32 ? `${title.slice(0, 32)}…` : title;

  return (
    <div style={{ marginBottom: 6 }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          padding: '4px 0',
        }}
      >
        <button
          type="button"
          onClick={onToggle}
          style={{
            padding: 2,
            border: 'none',
            background: 'none',
            cursor: 'pointer',
            color: 'var(--color-text-muted)',
          }}
        >
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </button>
        <span
          style={{
            flex: 1,
            fontSize: 12,
            color: 'var(--color-text)',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {truncated}
        </span>
        <a
          href={`/docs?docId=${doc.id}`}
          target="_blank"
          rel="noopener noreferrer"
          style={{ color: 'var(--color-text-muted)' }}
          title="Open in Docs"
        >
          <ExternalLink size={14} />
        </a>
      </div>
      {expanded && (
        <div
          style={{
            marginLeft: 20,
            maxHeight: 120,
            overflowY: 'auto',
            fontSize: 12,
            color: 'var(--color-text)',
            padding: '6px 8px',
            background: 'var(--color-bg)',
            border: '1px solid var(--color-border)',
            borderRadius: 6,
          }}
          dangerouslySetInnerHTML={{
            __html: DOMPurify.sanitize(
              loading ? '<em>Loading…</em>' : bodyHtml || '<em>No content</em>'
            ),
          }}
        />
      )}
    </div>
  );
}

DocRow.propTypes = {
  doc: PropTypes.shape({ id: PropTypes.number, title: PropTypes.string }).isRequired,
  expanded: PropTypes.bool.isRequired,
  onToggle: PropTypes.func.isRequired,
};

const ENTITY_TYPE_MAP = {
  hardware: 'hardware',
  compute: 'compute_unit',
  compute_unit: 'compute_unit',
  virtual_machine: 'compute_unit',
  docker_container: 'compute_unit',
  storage: 'storage',
  service: 'service',
};

function formatTelemetryRate(bytes) {
  if (bytes == null) return '—';
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB/s`;
  if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)} MB/s`;
  if (bytes >= 1e3) return `${(bytes / 1e3).toFixed(0)} KB/s`;
  return `${bytes} B/s`;
}

function SidebarTelemetryBlock({ node }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [discoveryData, setDiscoveryData] = useState(null);
  const hasProxmox = node?.data?.integration_config_id != null;
  const entityType = ENTITY_TYPE_MAP[node?.originalType] || null;
  const entityId = node?._refId;

  useEffect(() => {
    if (!hasProxmox || !entityType || !entityId) return;
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
  }, [hasProxmox, entityType, entityId]);

  useEffect(() => {
    if (node?.originalType !== 'service' || !entityId) {
      setDiscoveryData(null);
      return;
    }
    let cancelled = false;
    servicesApi
      .getDiscovery(entityId)
      .then((res) => {
        if (!cancelled) setDiscoveryData(res);
      })
      .catch(() => {
        if (!cancelled) setDiscoveryData(null);
      });
    return () => {
      cancelled = true;
    };
  }, [node?.originalType, entityId]);

  if (!hasProxmox && node?.originalType !== 'service') return null;

  if (loading) {
    return (
      <div style={{ marginBottom: 12 }}>
        <SectionTitle icon={Activity} title="Live Telemetry" />
        <div
          style={{
            background: 'var(--color-bg)',
            border: '1px solid var(--color-border)',
            borderRadius: 8,
            padding: 10,
            fontSize: 12,
            color: 'var(--color-text-muted)',
          }}
        >
          Loading…
        </div>
      </div>
    );
  }

  if (!data) return null;

  const cpuPct = data.cpu_pct != null ? Math.round(data.cpu_pct * 100) : null;
  const memUsed =
    data.mem_used_gb ?? (data.mem_used != null ? +(data.mem_used / 1073741824).toFixed(1) : null);
  const memTotal =
    data.mem_total_gb ??
    (data.mem_total != null ? +(data.mem_total / 1073741824).toFixed(1) : null);
  const diskUsed =
    data.disk_used_gb ??
    (data.rootfs_used != null ? +(data.rootfs_used / 1073741824).toFixed(1) : null);
  const diskTotal =
    data?.disk_total_gb ??
    (data?.rootfs_total != null ? +(data.rootfs_total / 1073741824).toFixed(1) : null);
  const statusLabel =
    data?.status === 'active' || data?.status === 'running' ? 'Running' : data?.status || null;

  const rows = [];
  if (statusLabel) rows.push({ label: 'Status', value: statusLabel });

  // Add Docker specific rows
  if (discoveryData?.docker) {
    const d = discoveryData.docker;
    if (d.error) {
      rows.push({ label: 'Docker Error', value: d.error });
    } else {
      rows.push({ label: 'Docker Status', value: d.status || d.raw_status || 'unknown' });
      if (d.cpu_pct != null) rows.push({ label: 'Docker CPU', value: `${d.cpu_pct}%` });
      if (d.mem_usage != null && d.mem_limit > 0) {
        const usageMb = (d.mem_usage / 1048576).toFixed(1);
        const pct = d.mem_pct != null ? ` (${d.mem_pct}%)` : '';
        rows.push({ label: 'Docker Mem', value: `${usageMb} MB${pct}` });
      }
    }
  }

  if (cpuPct != null) rows.push({ label: 'CPU', value: `${cpuPct}%` });
  if (memUsed != null && memTotal != null)
    rows.push({ label: 'Memory', value: `${memUsed} / ${memTotal} GB` });
  if (diskUsed != null && diskTotal != null)
    rows.push({ label: 'Disk', value: `${diskUsed} / ${diskTotal} GB` });
  if (data.net_rx != null || data.net_tx != null) {
    rows.push({
      label: 'Net',
      value: `↓ ${formatTelemetryRate(data.net_rx)} / ↑ ${formatTelemetryRate(data.net_tx)}`,
    });
  }
  if (data.netin != null || data.netout != null) {
    rows.push({
      label: 'Net',
      value: `↓ ${formatTelemetryRate(data.netin)} / ↑ ${formatTelemetryRate(data.netout)}`,
    });
  }
  if (data.uptime_s != null) {
    const s = data.uptime_s;
    const d = Math.floor(s / 86400);
    const h = Math.floor((s % 86400) / 3600);
    const m = Math.floor((s % 3600) / 60);
    rows.push({ label: 'Uptime', value: d > 0 ? `${d}d ${h}h` : h > 0 ? `${h}h ${m}m` : `${m}m` });
  }
  if (data.child_vms && (data.child_vms.running > 0 || data.child_vms.stopped > 0)) {
    rows.push({
      label: 'VMs',
      value: `${data.child_vms.running} running, ${data.child_vms.stopped} stopped`,
    });
  }
  if (data.child_cts && (data.child_cts.running > 0 || data.child_cts.stopped > 0)) {
    rows.push({
      label: 'CTs',
      value: `${data.child_cts.running} running, ${data.child_cts.stopped} stopped`,
    });
  }
  if (data.capacity_gb != null && data.used_gb != null) {
    const pct = data.capacity_gb > 0 ? Math.round((data.used_gb / data.capacity_gb) * 100) : 0;
    rows.push({ label: 'Capacity', value: `${data.used_gb} / ${data.capacity_gb} GB (${pct}%)` });
  }

  if (rows.length === 0) return null;

  return (
    <div style={{ marginBottom: 12 }}>
      <SectionTitle icon={Activity} title="Live Telemetry" />
      <div
        style={{
          background: 'var(--color-bg)',
          border: '1px solid var(--color-border)',
          borderRadius: 8,
          padding: '4px 10px',
        }}
      >
        {rows.map((row, index) => (
          <div
            key={row.label}
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              padding: '6px 0',
              borderBottom: index < rows.length - 1 ? '1px solid var(--color-border)' : 'none',
              gap: 8,
            }}
          >
            <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>{row.label}</span>
            <span
              style={{
                fontSize: 12,
                color: 'var(--color-text)',
                textAlign: 'right',
                wordBreak: 'break-word',
              }}
            >
              {row.value}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

SidebarTelemetryBlock.propTypes = { node: PropTypes.object };

export default function Sidebar({
  node = null,
  anchor = null,
  relationships = [],
  sysinfo = [],
  status = null,
  onClose,
  onUplinkChange = undefined,
  onOpenInHud = undefined,
  onBoundsChange = undefined,
  onMonitorAction = undefined,
}) {
  const [speed, setSpeed] = useState(1000);
  const [position, setPosition] = useState({ x: 24, y: 84 });
  const [expandedDocId, setExpandedDocId] = useState(null);
  const dragRef = useRef({ offsetX: 0, offsetY: 0, dragging: false, move: null, up: null });
  const debounceRef = useRef(null);
  const panelRef = useRef(null);

  const nodeId = node?.id || null;

  useEffect(() => {
    setExpandedDocId(null);
  }, [nodeId]);

  // Emit the panel's viewport-relative bounding rect whenever position changes so
  // the context menu can shift itself away from the panel.
  useEffect(() => {
    if (!node || !onBoundsChange) return;
    const panel = panelRef.current;
    if (!panel) return;
    const rafId = globalThis.requestAnimationFrame(() => {
      const r = panel.getBoundingClientRect();
      onBoundsChange({
        left: r.left,
        top: r.top,
        right: r.right,
        bottom: r.bottom,
        width: r.width,
        height: r.height,
      });
    });
    return () => globalThis.cancelAnimationFrame(rafId);
  }, [position, node, onBoundsChange]);

  // Clear bounds when the panel is hidden
  useEffect(() => {
    if (!node) onBoundsChange?.(null);
  }, [node, onBoundsChange]);

  useEffect(() => {
    if (!node) return;
    const nextSpeed = Number(
      node.data?.uplinkSpeed ??
        node.data?.upload_speed_mbps ??
        node.data?.download_speed_mbps ??
        1000
    );
    setSpeed(Number.isFinite(nextSpeed) && nextSpeed > 0 ? nextSpeed : 1000);
  }, [node]);

  useEffect(() => {
    if (!nodeId) return;
    if (!anchor) {
      setPosition({ x: 24, y: 84 });
      return;
    }

    const panel = panelRef.current;
    const panelWidth = panel?.offsetWidth || 340;
    const panelHeight = panel?.offsetHeight || 500;
    const parent = panel?.parentElement;
    const parentWidth = parent?.clientWidth || globalThis.innerWidth;
    const parentHeight = parent?.clientHeight || globalThis.innerHeight;
    const minX = 8;
    const minY = 8;
    const maxX = Math.max(8, parentWidth - panelWidth - 8);
    const maxY = Math.max(8, parentHeight - panelHeight - 8);
    const nextX = Math.min(maxX, Math.max(minX, anchor.x));
    const nextY = Math.min(maxY, Math.max(minY, anchor.y - panelHeight / 2));
    setPosition({ x: nextX, y: nextY });
  }, [anchor, nodeId]);

  useEffect(() => {
    if (!node || !anchor || dragRef.current.dragging) return;

    const panel = panelRef.current;
    const panelWidth = panel?.offsetWidth || 340;
    const panelHeight = panel?.offsetHeight || 500;
    const parent = panel?.parentElement;
    const parentWidth = parent?.clientWidth || globalThis.innerWidth;
    const parentHeight = parent?.clientHeight || globalThis.innerHeight;
    const minX = 8;
    const minY = 8;
    const maxX = Math.max(8, parentWidth - panelWidth - 8);
    const maxY = Math.max(8, parentHeight - panelHeight - 8);
    const nextX = Math.min(maxX, Math.max(minX, anchor.x));
    const nextY = Math.min(maxY, Math.max(minY, anchor.y - panelHeight / 2));
    setPosition({ x: nextX, y: nextY });
  }, [anchor, node]);

  useEffect(
    () => () => {
      if (debounceRef.current) globalThis.clearTimeout(debounceRef.current);

      if (dragRef.current.move) {
        globalThis.removeEventListener('pointermove', dragRef.current.move);
      }
      if (dragRef.current.up) {
        globalThis.removeEventListener('pointerup', dragRef.current.up);
      }
    },
    []
  );

  const statusRows = useMemo(() => {
    if (!status) return [];
    const rows = [
      { label: 'Effective', value: status.effectiveStatus || 'unknown' },
      { label: 'Model', value: status.modelStatus || '—' },
      { label: 'Override', value: status.overrideStatus || '—' },
      { label: 'Telemetry', value: status.telemetryStatus || 'unknown' },
    ];

    if (status.telemetryLastPolled) {
      rows.push({
        label: 'Last Polled',
        value: new Date(status.telemetryLastPolled).toLocaleString(),
      });
    }

    return rows;
  }, [status]);

  const handleSliderChange = (event) => {
    const nextSpeed = Number.parseInt(event.target.value, 10);
    setSpeed(nextSpeed);

    if (debounceRef.current) globalThis.clearTimeout(debounceRef.current);
    debounceRef.current = globalThis.setTimeout(() => {
      if (node?.id) onUplinkChange?.(node.id, nextSpeed);
    }, 80);
  };

  const startDrag = (event) => {
    if (event.button !== 0) return;
    const panel = panelRef.current;
    if (!panel) return;

    const rect = panel.getBoundingClientRect();
    dragRef.current.offsetX = event.clientX - rect.left;
    dragRef.current.offsetY = event.clientY - rect.top;
    dragRef.current.dragging = true;

    const onMove = (moveEvent) => {
      const width = rect.width;
      const height = rect.height;
      const minX = 8;
      const minY = 8;
      const maxX = Math.max(8, globalThis.innerWidth - width - 8);
      const maxY = Math.max(8, globalThis.innerHeight - height - 8);
      const x = Math.min(maxX, Math.max(minX, moveEvent.clientX - dragRef.current.offsetX));
      const y = Math.min(maxY, Math.max(minY, moveEvent.clientY - dragRef.current.offsetY));
      setPosition({ x, y });
    };

    const onUp = () => {
      dragRef.current.dragging = false;
      globalThis.removeEventListener('pointermove', onMove);
      globalThis.removeEventListener('pointerup', onUp);
      dragRef.current.move = null;
      dragRef.current.up = null;
    };

    dragRef.current.move = onMove;
    dragRef.current.up = onUp;
    globalThis.addEventListener('pointermove', onMove);
    globalThis.addEventListener('pointerup', onUp);
  };

  return (
    <AnimatePresence>
      {node && (
        <motion.div
          key={node.id}
          initial={{ opacity: 0, y: 10, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 8, scale: 0.98 }}
          transition={{ duration: 0.18, ease: 'easeOut' }}
          ref={panelRef}
          style={{
            position: 'absolute',
            left: position.x,
            top: position.y,
            width: 340,
            maxHeight: 'calc(100% - 24px)',
            background: 'var(--color-surface)',
            border: '1px solid var(--color-border)',
            borderRadius: 12,
            boxShadow: '0 12px 36px rgba(0,0,0,0.45)',
            color: 'var(--color-text)',
            zIndex: 220,
            overflow: 'hidden',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          <div
            onPointerDown={startDrag}
            style={{
              display: 'flex',
              alignItems: 'flex-start',
              justifyContent: 'space-between',
              padding: '10px 12px 8px',
              borderBottom: '1px solid var(--color-border)',
              background: 'var(--color-surface-secondary)',
              cursor: 'grab',
              userSelect: 'none',
            }}
          >
            <div>
              <div
                style={{
                  fontWeight: 700,
                  fontFamily: 'var(--font-mono, ui-monospace, monospace)',
                  fontSize: 17,
                  color: 'var(--color-text)',
                }}
              >
                {node.data?.alias || node.data?.label}
              </div>
              <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 2 }}>
                {node.originalType || node.data?.type || 'node'}
              </div>
            </div>

            <button
              type="button"
              onClick={onClose}
              aria-label="Close details"
              style={{
                width: 24,
                height: 24,
                borderRadius: 999,
                border: '1px solid var(--color-border)',
                background: 'transparent',
                color: 'var(--color-text-muted)',
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                cursor: 'pointer',
                transition: 'all 0.15s ease',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.color = 'var(--color-text)';
                e.currentTarget.style.background = 'var(--color-bg)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.color = 'var(--color-text-muted)';
                e.currentTarget.style.background = 'transparent';
              }}
            >
              <X size={14} strokeWidth={2} />
            </button>
          </div>

          <div style={{ overflowY: 'auto', padding: 12 }}>
            <div
              style={{
                background: 'var(--color-bg)',
                border: '1px solid var(--color-border)',
                borderRadius: 10,
                padding: 10,
                marginBottom: 12,
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>Uplink Speed</span>
                <span style={{ fontSize: 12, color: 'var(--color-primary)', fontWeight: 700 }}>
                  {formatSpeedLabel(speed)}
                </span>
              </div>
              <input
                type="range"
                min="100"
                max="100000"
                step="100"
                value={speed}
                onChange={handleSliderChange}
                style={{ width: '100%' }}
              />
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  fontSize: 11,
                  color: 'var(--color-text-muted)',
                  marginTop: 4,
                }}
              >
                <span>100M</span>
                <span>100G</span>
              </div>
            </div>

            {statusRows.length > 0 && (
              <div style={{ marginBottom: 12 }}>
                <SectionTitle icon={Activity} title="Status" />
                <div
                  style={{
                    background: 'var(--color-bg)',
                    border: '1px solid var(--color-border)',
                    borderRadius: 8,
                    padding: '4px 10px',
                  }}
                >
                  {statusRows.map((row, index) => (
                    <div
                      key={row.label}
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        padding: '6px 0',
                        borderBottom:
                          index < statusRows.length - 1 ? '1px solid var(--color-border)' : 'none',
                        gap: 8,
                      }}
                    >
                      <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
                        {row.label}
                      </span>
                      <span
                        style={{
                          fontSize: 12,
                          color: 'var(--color-text)',
                          textTransform: 'capitalize',
                          textAlign: 'right',
                        }}
                      >
                        {String(row.value).replaceAll('_', ' ')}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <SidebarTelemetryBlock node={node} />

            {node?.originalType === 'hardware' && onMonitorAction && (
              <div
                style={{
                  marginBottom: 12,
                  opacity:
                    node.data?.monitor_status != null && node.data?.monitor_enabled === false
                      ? 0.6
                      : 1,
                }}
              >
                <SectionTitle icon={Radio} title="Monitor" />
                {node.data?.monitor_status != null ? (
                  <>
                    <div
                      style={{
                        background: 'var(--color-bg)',
                        border: '1px solid var(--color-border)',
                        borderRadius: 8,
                        padding: '4px 10px',
                      }}
                    >
                      {[
                        { label: 'Status', value: node.data.monitor_status },
                        node.data.monitor_latency_ms != null && {
                          label: 'Latency',
                          value: `${Math.round(node.data.monitor_latency_ms)} ms`,
                        },
                        node.data.monitor_uptime_pct_24h != null && {
                          label: 'Uptime (24h)',
                          value: `${node.data.monitor_uptime_pct_24h.toFixed(1)}%`,
                        },
                        node.data.monitor_last_checked_at && {
                          label: 'Last Checked',
                          value: new Date(node.data.monitor_last_checked_at).toLocaleString(),
                        },
                      ]
                        .filter(Boolean)
                        .map((row, index, arr) => (
                          <div
                            key={row.label}
                            style={{
                              display: 'flex',
                              justifyContent: 'space-between',
                              padding: '6px 0',
                              borderBottom:
                                index < arr.length - 1 ? '1px solid var(--color-border)' : 'none',
                              gap: 8,
                            }}
                          >
                            <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
                              {row.label}
                            </span>
                            <span
                              style={{
                                fontSize: 12,
                                fontWeight: row.label === 'Status' ? 700 : 400,
                                color:
                                  row.label === 'Status'
                                    ? node.data.monitor_status === 'up'
                                      ? 'var(--color-online)'
                                      : node.data.monitor_status === 'down'
                                        ? 'var(--color-danger)'
                                        : 'var(--color-text-muted)'
                                    : 'var(--color-text)',
                                textAlign: 'right',
                              }}
                            >
                              {row.value}
                            </span>
                          </div>
                        ))}
                    </div>
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        marginTop: 6,
                        gap: 8,
                      }}
                    >
                      <span
                        style={{
                          fontSize: 12,
                          display: 'flex',
                          alignItems: 'center',
                          gap: 6,
                        }}
                      >
                        <span
                          style={{
                            display: 'inline-block',
                            width: 8,
                            height: 8,
                            borderRadius: '50%',
                            background:
                              node.data.monitor_enabled === false
                                ? 'var(--color-text-muted)'
                                : 'var(--color-online)',
                          }}
                          title={
                            node.data.monitor_enabled === false ? 'Monitoring off' : 'Monitoring on'
                          }
                        />
                        <span style={{ color: 'var(--color-text-muted)' }}>
                          {node.data.monitor_enabled === false ? 'Off' : 'On'}
                        </span>
                      </span>
                      <button
                        type="button"
                        onClick={() => onMonitorAction('monitor_toggle')}
                        style={{
                          padding: '4px 10px',
                          fontSize: 12,
                          borderRadius: 4,
                          border: '1px solid var(--color-border)',
                          background:
                            node.data.monitor_enabled === false
                              ? 'var(--color-primary)'
                              : 'var(--color-bg)',
                          color:
                            node.data.monitor_enabled === false
                              ? 'var(--color-bg)'
                              : 'var(--color-text)',
                          cursor: 'pointer',
                          fontWeight: 500,
                        }}
                      >
                        {node.data.monitor_enabled === false ? 'Enable' : 'Disable'}
                      </button>
                    </div>
                    <button
                      type="button"
                      onClick={() => onMonitorAction('monitor_check_now')}
                      style={{
                        marginTop: 6,
                        width: '100%',
                        padding: '6px 10px',
                        fontSize: 12,
                        borderRadius: 4,
                        border: '1px solid var(--color-border)',
                        background: 'var(--color-bg)',
                        color: 'var(--color-text)',
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        gap: 6,
                      }}
                    >
                      <Activity size={14} />
                      Check Now
                    </button>
                  </>
                ) : (
                  <button
                    type="button"
                    onClick={() => onMonitorAction('monitor_create')}
                    style={{
                      width: '100%',
                      padding: '8px 10px',
                      fontSize: 12,
                      borderRadius: 8,
                      border: '1px solid var(--color-border)',
                      background: 'var(--color-bg)',
                      color: 'var(--color-text)',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: 6,
                    }}
                  >
                    <Radio size={14} />
                    Enable Monitoring
                  </button>
                )}
              </div>
            )}

            {node?.data?.docs?.length > 0 && (
              <div style={{ marginBottom: 12 }}>
                <SectionTitle icon={FileText} title="Documents" />
                {node.data.docs.map((doc) => (
                  <DocRow
                    key={doc.id}
                    doc={doc}
                    expanded={expandedDocId === doc.id}
                    onToggle={() => setExpandedDocId(expandedDocId === doc.id ? null : doc.id)}
                  />
                ))}
              </div>
            )}

            {sysinfo.length > 0 && (
              <div style={{ marginBottom: 12 }}>
                <SectionTitle icon={Info} title="System Info" />
                <div
                  style={{
                    background: 'var(--color-bg)',
                    border: '1px solid var(--color-border)',
                    borderRadius: 8,
                    padding: '4px 10px',
                  }}
                >
                  {sysinfo.map((row, index) => (
                    <div
                      key={row.key}
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        padding: '6px 0',
                        borderBottom:
                          index < sysinfo.length - 1 ? '1px solid var(--color-border)' : 'none',
                        gap: 8,
                      }}
                    >
                      <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
                        {row.label}
                      </span>
                      <span
                        style={{
                          fontSize: 12,
                          color: 'var(--color-text)',
                          textAlign: 'right',
                          wordBreak: 'break-word',
                        }}
                      >
                        {row.value}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {relationships.length > 0 && (
              <div style={{ marginBottom: 12 }}>
                <SectionTitle icon={Link2} title="Relationships" />
                {relationships.map((rel) => (
                  <div
                    key={`${rel.direction}-${rel.relation}-${rel.nodeId}`}
                    style={{
                      background: 'var(--color-bg)',
                      border: '1px solid var(--color-border)',
                      borderRadius: 8,
                      padding: '8px 10px',
                      marginBottom: 6,
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                      <span style={{ fontSize: 12, color: 'var(--color-text)' }}>
                        {rel.nodeLabel}
                      </span>
                      <span
                        style={{
                          fontSize: 11,
                          color: 'var(--color-text-muted)',
                          textTransform: 'capitalize',
                        }}
                      >
                        {rel.nodeType}
                      </span>
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--color-primary)', marginTop: 3 }}>
                      {rel.direction === 'out' ? '→' : '←'}{' '}
                      {String(rel.relation).replaceAll('_', ' ')}
                    </div>
                    {rel.nodeAddress && (
                      <div
                        style={{
                          fontSize: 11,
                          color: 'var(--color-text-muted)',
                          marginTop: 2,
                          fontFamily: 'ui-monospace, monospace',
                        }}
                      >
                        {rel.nodeAddress}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}

            {node.data?.docs?.length > 0 && (
              <div style={{ marginBottom: 12 }}>
                <SectionTitle icon={FileText} title="Docs" />
                <div
                  style={{
                    background: 'var(--color-bg)',
                    border: '1px solid var(--color-border)',
                    borderRadius: 8,
                    padding: '4px 10px',
                  }}
                >
                  {node.data.docs.map((doc, index) => (
                    <div
                      key={doc.id}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        padding: '6px 0',
                        borderBottom:
                          index < node.data.docs.length - 1
                            ? '1px solid var(--color-border)'
                            : 'none',
                        gap: 8,
                      }}
                    >
                      <span style={{ fontSize: 13 }}>📄</span>
                      <a
                        href={`/docs?docId=${doc.id}`}
                        style={{
                          fontSize: 12,
                          color: 'var(--color-primary)',
                          textDecoration: 'none',
                        }}
                        title={`Open ${doc.title || 'document'}`}
                      >
                        {doc.title}
                      </a>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <button
              type="button"
              onClick={() => onOpenInHud?.(node)}
              style={{
                width: '100%',
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 6,
                border: '1px solid var(--color-border)',
                borderRadius: 8,
                background: 'var(--color-surface-secondary)',
                color: 'var(--color-primary)',
                padding: '8px 10px',
                fontSize: 12,
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              <ExternalLink size={13} />
              Open in HUD
            </button>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

Sidebar.propTypes = {
  node: PropTypes.shape({
    id: PropTypes.string,
    originalType: PropTypes.string,
    data: PropTypes.shape({
      docs: PropTypes.arrayOf(
        PropTypes.shape({
          id: PropTypes.number,
          title: PropTypes.string,
        })
      ),
    }),
  }),
  anchor: PropTypes.shape({
    x: PropTypes.number,
    y: PropTypes.number,
  }),
  relationships: PropTypes.arrayOf(
    PropTypes.shape({
      direction: PropTypes.string,
      relation: PropTypes.string,
      nodeId: PropTypes.string,
      nodeLabel: PropTypes.string,
      nodeType: PropTypes.string,
      nodeAddress: PropTypes.string,
    })
  ),
  sysinfo: PropTypes.arrayOf(
    PropTypes.shape({
      key: PropTypes.string,
      label: PropTypes.string,
      value: PropTypes.string,
    })
  ),
  status: PropTypes.shape({
    effectiveStatus: PropTypes.string,
    modelStatus: PropTypes.string,
    overrideStatus: PropTypes.string,
    telemetryStatus: PropTypes.string,
    telemetryLastPolled: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
  }),
  onClose: PropTypes.func.isRequired,
  onUplinkChange: PropTypes.func,
  onOpenInHud: PropTypes.func,
  /** Called with { left, top, right, bottom } whenever the panel repositions, or null when hidden */
  onBoundsChange: PropTypes.func,
  /** Called with 'monitor_create' | 'monitor_toggle' | 'monitor_check_now' for hardware nodes */
  onMonitorAction: PropTypes.func,
};
