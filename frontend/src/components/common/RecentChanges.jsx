import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Clock } from 'lucide-react';
import { adminApi } from '../../api/client';
import TimestampCell from '../TimestampCell.jsx';

// ── Route map ─────────────────────────────────────────────────────────────

const ENTITY_ROUTE = {
  hardware: '/hardware',
  compute:  '/compute-units',
  service:  '/services',
  storage:  '/storage',
  network:  '/networks',
  misc:     '/misc',
};

const ENTITY_LABEL = {
  hardware: 'HW',
  compute:  'CU',
  service:  'SVC',
  storage:  'ST',
  network:  'NET',
  misc:     'MISC',
};

const ENTITY_COLOR = {
  hardware: '#7c3aed',
  compute:  '#2563eb',
  service:  '#059669',
  storage:  '#d97706',
  network:  '#0891b2',
  misc:     '#db2777',
};

// ── Component ─────────────────────────────────────────────────────────────

export default function RecentChanges() {
  const navigate = useNavigate();
  const [open, setOpen]       = useState(false);
  const [items, setItems]     = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState(null);
  const panelRef = useRef(null);

  // Fetch on open
  useEffect(() => {
    if (!open) return;
    setLoading(true);
    setError(null);
    adminApi.recentChanges(10)
      .then((res) => setItems(res.data ?? []))
      .catch((err) => setError(err.message || 'Failed to load'))
      .finally(() => setLoading(false));
  }, [open]);

  // Close on outside click
  const handleMouseDown = useCallback((e) => {
    if (panelRef.current && !panelRef.current.contains(e.target)) {
      setOpen(false);
    }
  }, []);

  useEffect(() => {
    if (open) {
      document.addEventListener('mousedown', handleMouseDown);
    }
    return () => document.removeEventListener('mousedown', handleMouseDown);
  }, [open, handleMouseDown]);

  function handleItemClick(item) {
    setOpen(false);
    navigate(ENTITY_ROUTE[item.entity_type] ?? '/');
  }

  return (
    <div ref={panelRef} style={{ position: 'relative' }}>
      {/* Trigger button */}
      <button
        title="Recent Changes"
        aria-label="Recent Changes"
        onClick={() => setOpen((v) => !v)}
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: 36,
          height: 36,
          background: open ? 'var(--color-border)' : 'transparent',
          border: '1px solid var(--color-border)',
          borderRadius: 8,
          cursor: 'pointer',
          color: open ? 'var(--color-primary)' : 'var(--color-text-muted)',
          transition: 'all 0.15s',
          flexShrink: 0,
        }}
        onMouseEnter={(e) => { if (!open) e.currentTarget.style.borderColor = 'var(--color-primary)'; }}
        onMouseLeave={(e) => { if (!open) e.currentTarget.style.borderColor = 'var(--color-border)'; }}
      >
        <Clock size={16} />
      </button>

      {/* Dropdown panel */}
      {open && (
        <div
          style={{
            position: 'fixed',
            top: 'calc(var(--header-height, 52px) + 6px)',
            right: 16,
            zIndex: 300,
            width: 320,
            maxHeight: 440,
            background: 'var(--color-surface)',
            border: '1px solid var(--color-border)',
            borderRadius: 10,
            boxShadow: '0 8px 32px rgba(0,0,0,0.35)',
            overflow: 'hidden',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          {/* Header */}
          <div style={{
            padding: '10px 14px 8px',
            borderBottom: '1px solid var(--color-border)',
            fontSize: 12,
            fontWeight: 700,
            color: 'var(--color-text)',
            letterSpacing: '0.04em',
            display: 'flex',
            alignItems: 'center',
            gap: 6,
          }}>
            <Clock size={13} style={{ color: 'var(--color-primary)', flexShrink: 0 }} />
            Recent Changes
          </div>

          {/* Body */}
          <div style={{ overflowY: 'auto', flex: 1 }}>
            {loading && (
              <div style={{ padding: '20px 14px', fontSize: 12, color: 'var(--color-text-muted)', textAlign: 'center' }}>
                Loading…
              </div>
            )}
            {!loading && error && (
              <div style={{ padding: '12px 14px', fontSize: 12, color: 'var(--color-danger, #e74c3c)' }}>
                {error}
              </div>
            )}
            {!loading && !error && items.length === 0 && (
              <div style={{ padding: '20px 14px', fontSize: 12, color: 'var(--color-text-muted)', textAlign: 'center' }}>
                No recent changes found.
              </div>
            )}
            {!loading && !error && items.map((item, i) => {
              const color = ENTITY_COLOR[item.entity_type] ?? '#888';
              return (
                <button
                  key={`${item.entity_type}-${item.entity_id}-${i}`}
                  onClick={() => handleItemClick(item)}
                  style={{
                    width: '100%',
                    background: 'transparent',
                    border: 'none',
                    padding: '9px 14px',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 10,
                    cursor: 'pointer',
                    textAlign: 'left',
                    borderBottom: '1px solid var(--color-border)',
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--color-bg)'; }}
                  onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
                >
                  {/* Type chip */}
                  <span style={{
                    fontSize: 9,
                    fontWeight: 700,
                    letterSpacing: '0.06em',
                    color: '#fff',
                    background: color,
                    borderRadius: 3,
                    padding: '2px 5px',
                    flexShrink: 0,
                    minWidth: 32,
                    textAlign: 'center',
                  }}>
                    {ENTITY_LABEL[item.entity_type] ?? item.entity_type.toUpperCase()}
                  </span>

                  {/* Name */}
                  <span style={{
                    flex: 1,
                    fontSize: 12,
                    color: 'var(--color-text)',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    fontWeight: 500,
                  }}>
                    {item.name}
                  </span>

                  {/* Relative time */}
                  <span style={{
                    fontSize: 10,
                    color: 'var(--color-text-muted)',
                    flexShrink: 0,
                  }}>
                    <TimestampCell isoString={item.updated_at} />
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
