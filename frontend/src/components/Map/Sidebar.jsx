import React, { useEffect, useMemo, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { X, ExternalLink, Link2, Activity, Info } from 'lucide-react';
import { AnimatePresence, motion } from 'framer-motion';

function formatSpeedLabel(mbps) {
  const value = Number(mbps) || 0;
  if (value >= 1000) {
    return `${(value / 1000).toFixed(1).replace(/\.0$/, '')} Gbps`;
  }
  return `${Math.round(value)} Mbps`;
}

function SectionTitle({ icon: Icon, title }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 6 }}>
      <Icon size={14} />
      <span>{title}</span>
    </div>
  );
}

SectionTitle.propTypes = {
  icon: PropTypes.elementType.isRequired,
  title: PropTypes.string.isRequired,
};

export default function Sidebar({ node, anchor, relationships, sysinfo, status, onClose, onUplinkChange, onOpenInHud }) {
  const [speed, setSpeed] = useState(1000);
  const [position, setPosition] = useState({ x: 24, y: 84 });
  const dragRef = useRef({ offsetX: 0, offsetY: 0, dragging: false, move: null, up: null });
  const debounceRef = useRef(null);
  const panelRef = useRef(null);

  const nodeId = node?.id || null;

  useEffect(() => {
    if (!node) return;
    const nextSpeed = Number(
      node.data?.uplinkSpeed
      ?? node.data?.upload_speed_mbps
      ?? node.data?.download_speed_mbps
      ?? 1000,
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
    const nextY = Math.min(maxY, Math.max(minY, anchor.y - (panelHeight / 2)));
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
    const nextY = Math.min(maxY, Math.max(minY, anchor.y - (panelHeight / 2)));
    setPosition({ x: nextX, y: nextY });
  }, [anchor, node]);

  useEffect(() => () => {
    if (debounceRef.current) globalThis.clearTimeout(debounceRef.current);

    if (dragRef.current.move) {
      globalThis.removeEventListener('pointermove', dragRef.current.move);
    }
    if (dragRef.current.up) {
      globalThis.removeEventListener('pointerup', dragRef.current.up);
    }
  }, []);

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
              <div style={{ fontWeight: 700, fontFamily: 'var(--font-mono, ui-monospace, monospace)', fontSize: 17, color: 'var(--color-text)' }}>
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
                <span style={{ fontSize: 12, color: 'var(--color-primary)', fontWeight: 700 }}>{formatSpeedLabel(speed)}</span>
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
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--color-text-muted)', marginTop: 4 }}>
                <span>100M</span>
                <span>100G</span>
              </div>
            </div>

            {statusRows.length > 0 && (
              <div style={{ marginBottom: 12 }}>
                <SectionTitle icon={Activity} title="Status" />
                <div style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', borderRadius: 8, padding: '4px 10px' }}>
                  {statusRows.map((row, index) => (
                    <div key={row.label} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: index < statusRows.length - 1 ? '1px solid var(--color-border)' : 'none', gap: 8 }}>
                      <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>{row.label}</span>
                      <span style={{ fontSize: 12, color: 'var(--color-text)', textTransform: 'capitalize', textAlign: 'right' }}>{String(row.value).replaceAll('_', ' ')}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {sysinfo.length > 0 && (
              <div style={{ marginBottom: 12 }}>
                <SectionTitle icon={Info} title="System Info" />
                <div style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', borderRadius: 8, padding: '4px 10px' }}>
                  {sysinfo.map((row, index) => (
                    <div key={row.key} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: index < sysinfo.length - 1 ? '1px solid var(--color-border)' : 'none', gap: 8 }}>
                      <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>{row.label}</span>
                      <span style={{ fontSize: 12, color: 'var(--color-text)', textAlign: 'right', wordBreak: 'break-word' }}>{row.value}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {relationships.length > 0 && (
              <div style={{ marginBottom: 12 }}>
                <SectionTitle icon={Link2} title="Relationships" />
                {relationships.map((rel) => (
                  <div key={`${rel.direction}-${rel.relation}-${rel.nodeId}`} style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', borderRadius: 8, padding: '8px 10px', marginBottom: 6 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                      <span style={{ fontSize: 12, color: 'var(--color-text)' }}>{rel.nodeLabel}</span>
                      <span style={{ fontSize: 11, color: 'var(--color-text-muted)', textTransform: 'capitalize' }}>{rel.nodeType}</span>
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--color-primary)', marginTop: 3 }}>
                      {rel.direction === 'out' ? '→' : '←'} {String(rel.relation).replaceAll('_', ' ')}
                    </div>
                    {rel.nodeAddress && (
                      <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 2, fontFamily: 'ui-monospace, monospace' }}>
                        {rel.nodeAddress}
                      </div>
                    )}
                  </div>
                ))}
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
    data: PropTypes.object,
  }),
  anchor: PropTypes.shape({
    x: PropTypes.number,
    y: PropTypes.number,
  }),
  relationships: PropTypes.arrayOf(PropTypes.shape({
    direction: PropTypes.string,
    relation: PropTypes.string,
    nodeId: PropTypes.string,
    nodeLabel: PropTypes.string,
    nodeType: PropTypes.string,
    nodeAddress: PropTypes.string,
  })),
  sysinfo: PropTypes.arrayOf(PropTypes.shape({
    key: PropTypes.string,
    label: PropTypes.string,
    value: PropTypes.string,
  })),
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
};

Sidebar.defaultProps = {
  node: null,
  anchor: null,
  relationships: [],
  sysinfo: [],
  status: null,
  onUplinkChange: undefined,
  onOpenInHud: undefined,
};
