import React, { useState, useEffect, useRef } from 'react';
import { environmentsApi } from '../../api/client';

export default function EnvironmentCombobox({ value, onChange }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [options, setOptions] = useState(null); // null = not yet loaded
  const [creating, setCreating] = useState(false);
  const containerRef = useRef(null);
  const inputRef = useRef(null);

  const selected = options?.find((e) => e.id === value) ?? null;

  // Lazy-load environments on first open
  useEffect(() => {
    if (!open || options !== null) return;
    environmentsApi
      .list()
      .then((r) => setOptions(r.data))
      .catch(() => setOptions([]));
  }, [open, options]);

  // Close dropdown on outside click
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

  const filtered = options
    ? options.filter((e) => e.name.toLowerCase().includes(query.toLowerCase()))
    : [];

  const showCreate =
    query.trim().length > 0 &&
    !filtered.some((e) => e.name.toLowerCase() === query.trim().toLowerCase());

  const handleOpen = () => {
    setOpen(true);
    setTimeout(() => inputRef.current?.focus(), 0);
  };

  const handleSelect = (env) => {
    onChange(env.id);
    setOpen(false);
    setQuery('');
  };

  const handleCreate = async () => {
    const name = query.trim();
    if (!name || creating) return;
    setCreating(true);
    try {
      await environmentsApi.create({ name });
    } catch {
      // 409 conflict is fine — we'll find it in the re-fetched list
    }
    try {
      const listRes = await environmentsApi.list();
      setOptions(listRes.data);
      const match = listRes.data.find((e) => e.name.toLowerCase() === name.toLowerCase());
      if (match) onChange(match.id);
    } catch {
      /* ignore */
    }
    setCreating(false);
    setOpen(false);
    setQuery('');
  };

  const handleClear = (e) => {
    e.stopPropagation();
    onChange(null);
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Escape') {
      setOpen(false);
      setQuery('');
    }
    if (e.key === 'Enter' && showCreate) {
      e.preventDefault();
      handleCreate();
    }
  };

  return (
    <div ref={containerRef} style={{ position: 'relative' }}>
      {/* ── Selected chip ── */}
      {selected && !open ? (
        <div
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            background: 'var(--color-surface-alt, var(--color-bg))',
            border: '1px solid var(--color-border)',
            borderRadius: 20,
            padding: '4px 10px',
            cursor: 'pointer',
            fontSize: 13,
          }}
          onClick={handleOpen}
        >
          {selected.color && (
            <span
              style={{
                width: 9,
                height: 9,
                borderRadius: '50%',
                background: selected.color,
                flexShrink: 0,
              }}
            />
          )}
          {selected.name}
          <button
            type="button"
            onClick={handleClear}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--color-text-muted)',
              cursor: 'pointer',
              padding: 0,
              lineHeight: 1,
              fontSize: 15,
              marginLeft: 2,
            }}
          >
            ×
          </button>
        </div>
      ) : (
        /* ── Search input ── */
        <input
          ref={inputRef}
          type="text"
          placeholder="Search or create environment…"
          value={query}
          onFocus={() => setOpen(true)}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onKeyDown={handleKeyDown}
          style={{ width: '100%' }}
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
            zIndex: 500,
            background: 'var(--color-surface)',
            border: '1px solid var(--color-border)',
            borderRadius: 8,
            maxHeight: 220,
            overflowY: 'auto',
            boxShadow: '0 4px 16px rgba(0,0,0,0.3)',
          }}
        >
          {options === null ? (
            <div style={{ padding: '10px 14px', color: 'var(--color-text-muted)', fontSize: 13 }}>
              Loading…
            </div>
          ) : (
            <>
              {filtered.length === 0 && !showCreate && (
                <div
                  style={{ padding: '10px 14px', color: 'var(--color-text-muted)', fontSize: 13 }}
                >
                  No environments found
                </div>
              )}

              {filtered.map((env) => (
                <div
                  key={env.id}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    handleSelect(env);
                  }}
                  style={{
                    padding: '8px 14px',
                    cursor: 'pointer',
                    fontSize: 13,
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    background: value === env.id ? 'var(--color-glow)' : 'transparent',
                    transition: 'background 0.1s',
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background = 'var(--color-glow)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background =
                      value === env.id ? 'var(--color-glow)' : 'transparent';
                  }}
                >
                  {env.color && (
                    <span
                      style={{
                        width: 9,
                        height: 9,
                        borderRadius: '50%',
                        background: env.color,
                        flexShrink: 0,
                      }}
                    />
                  )}
                  <span style={{ flex: 1 }}>{env.name}</span>
                  {env.usage_count > 0 && (
                    <span style={{ color: 'var(--color-text-muted)', fontSize: 11 }}>
                      {env.usage_count}
                    </span>
                  )}
                </div>
              ))}

              {showCreate && (
                <div
                  onMouseDown={(e) => {
                    e.preventDefault();
                    handleCreate();
                  }}
                  style={{
                    padding: '8px 14px',
                    cursor: creating ? 'wait' : 'pointer',
                    fontSize: 13,
                    color: 'var(--color-primary)',
                    borderTop: filtered.length > 0 ? '1px solid var(--color-border)' : 'none',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 6,
                    transition: 'background 0.1s',
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background = 'var(--color-glow)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = 'transparent';
                  }}
                >
                  ＋ Create &ldquo;{query.trim()}&rdquo; as new environment
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
