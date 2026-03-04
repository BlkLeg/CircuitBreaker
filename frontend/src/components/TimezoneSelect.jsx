import React, { useState, useRef, useEffect } from 'react';
import { useTimezones } from '../hooks/useTimezones.js';

const PINNED_TIMEZONES = [
  'UTC',
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Los_Angeles',
  'America/Phoenix',
  'Europe/London',
  'Europe/Paris',
  'Europe/Berlin',
  'Asia/Tokyo',
  'Asia/Shanghai',
  'Australia/Sydney',
];

const MAX_RESULTS = 50;

/**
 * Searchable combobox for selecting an IANA timezone.
 * Props:
 *   value    {string}   — currently selected IANA timezone string
 *   onChange {function} — called with the new timezone string
 *   disabled {bool}     — disables the input
 */
export default function TimezoneSelect({ value, onChange, disabled = false }) {
  const { timezones, loading } = useTimezones();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const containerRef = useRef(null);
  const inputRef = useRef(null);

  // Build the display list: pinned entries first, then sorted remainder
  const displayList = React.useMemo(() => {
    if (!timezones.length) return PINNED_TIMEZONES;
    const tzSet = new Set(timezones);
    const pinned = PINNED_TIMEZONES.filter((tz) => tzSet.has(tz));
    const rest = timezones.filter((tz) => !PINNED_TIMEZONES.includes(tz));
    return [...pinned, ...rest];
  }, [timezones]);

  // Filter by query
  const filtered = React.useMemo(() => {
    if (!query.trim()) return displayList.slice(0, MAX_RESULTS);
    const lower = query.toLowerCase();
    return displayList.filter((tz) => tz.toLowerCase().includes(lower)).slice(0, MAX_RESULTS);
  }, [query, displayList]);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    const handler = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setOpen(false);
        setQuery('');
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const handleOpen = () => {
    if (disabled) return;
    setOpen(true);
    setQuery('');
    setTimeout(() => inputRef.current?.focus(), 0);
  };

  const handleSelect = (tz) => {
    onChange(tz);
    setOpen(false);
    setQuery('');
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Escape') { setOpen(false); setQuery(''); }
    if (e.key === 'Enter' && filtered.length > 0) {
      e.preventDefault();
      handleSelect(filtered[0]);
    }
  };

  // Loading skeleton
  if (loading) {
    return (
      <div
        style={{
          height: 36,
          background: 'var(--color-surface-alt, var(--color-bg))',
          border: '1px solid var(--color-border)',
          borderRadius: 6,
          animation: 'pulse 1.5s ease-in-out infinite',
          opacity: 0.5,
        }}
        aria-label="Loading timezones…"
      />
    );
  }

  return (
    <div ref={containerRef} style={{ position: 'relative' }}>
      {/* ── Closed display / trigger ── */}
      {!open ? (
        <button
          type="button"
          onClick={handleOpen}
          disabled={disabled}
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            width: '100%',
            padding: '7px 12px',
            background: 'var(--color-surface-alt, var(--color-bg))',
            border: '1px solid var(--color-border)',
            borderRadius: 6,
            color: value ? 'var(--color-text)' : 'var(--color-text-muted)',
            fontSize: 13,
            cursor: disabled ? 'not-allowed' : 'pointer',
            textAlign: 'left',
            opacity: disabled ? 0.6 : 1,
          }}
        >
          <span>🌍&nbsp; {value || 'Select timezone…'}</span>
          <span style={{ color: 'var(--color-text-muted)', fontSize: 11 }}>▼</span>
        </button>
      ) : (
        /* ── Search input ── */
        <input
          ref={inputRef}
          type="text"
          placeholder="Search timezones…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          style={{
            width: '100%',
            padding: '7px 12px',
            background: 'var(--color-surface-alt, var(--color-bg))',
            border: '1px solid var(--color-primary)',
            borderRadius: 6,
            color: 'var(--color-text)',
            fontSize: 13,
            boxSizing: 'border-box',
            outline: 'none',
          }}
        />
      )}

      {/* ── Dropdown ── */}
      {open && (
        <div
          style={{
            position: 'absolute',
            top: 'calc(100% + 4px)',
            left: 0,
            right: 0,
            zIndex: 600,
            background: 'var(--color-surface)',
            border: '1px solid var(--color-border)',
            borderRadius: 8,
            maxHeight: 240,
            overflowY: 'auto',
            boxShadow: '0 4px 20px rgba(0,0,0,0.4)',
          }}
        >
          {filtered.length === 0 ? (
            <div style={{ padding: '10px 14px', color: 'var(--color-text-muted)', fontSize: 13 }}>
              No timezones match &quot;{query}&quot;
            </div>
          ) : (
            filtered.map((tz) => {
              const isPinned = PINNED_TIMEZONES.includes(tz) && !query.trim();
              return (
                <div
                  key={tz}
                  onMouseDown={(e) => { e.preventDefault(); handleSelect(tz); }}
                  style={{
                    padding: '8px 14px',
                    fontSize: 13,
                    cursor: 'pointer',
                    color: tz === value ? 'var(--color-primary)' : 'var(--color-text)',
                    background: tz === value ? 'var(--color-glow, rgba(99,179,237,0.08))' : 'transparent',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    borderBottom: isPinned && tz === PINNED_TIMEZONES[PINNED_TIMEZONES.length - 1]
                      ? '1px solid var(--color-border)'
                      : 'none',
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--color-surface-alt, rgba(255,255,255,0.05))'; }}
                  onMouseLeave={(e) => { e.currentTarget.style.background = tz === value ? 'var(--color-glow, rgba(99,179,237,0.08))' : 'transparent'; }}
                >
                  {tz === value && <span style={{ fontSize: 10, color: 'var(--color-primary)' }}>✓</span>}
                  {tz}
                </div>
              );
            })
          )}
          {!query.trim() && filtered.length === MAX_RESULTS && (
            <div style={{ padding: '6px 14px', fontSize: 11, color: 'var(--color-text-muted)', borderTop: '1px solid var(--color-border)' }}>
              Type to search all timezones…
            </div>
          )}
        </div>
      )}
    </div>
  );
}
