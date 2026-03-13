import React, { useCallback, useEffect, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { networksApi } from '../../api/client.jsx';
import { useToast } from '../common/Toast';

function isValidCidr(value) {
  const input = value.trim();
  const slashIndex = input.indexOf('/');
  if (slashIndex <= 0 || slashIndex === input.length - 1) return false;

  const address = input.slice(0, slashIndex);
  const prefix = Number(input.slice(slashIndex + 1));
  if (!Number.isInteger(prefix) || prefix < 0 || prefix > 32) return false;

  const octets = address.split('.');
  if (octets.length !== 4) return false;
  return octets.every((octet) => {
    if (!/^\d{1,3}$/.test(octet)) return false;
    const valueNum = Number(octet);
    return valueNum >= 0 && valueNum <= 255;
  });
}

export default function NetworkSelectorDropdown({ value, onChange, disabled = false }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [networks, setNetworks] = useState([]);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState('');
  const [newCidr, setNewCidr] = useState('');
  const [cidrError, setCidrError] = useState('');
  const containerRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    networksApi
      .list({ limit: 200 })
      .then((res) => {
        const items = res.data?.items ?? res.data ?? [];
        setNetworks(Array.isArray(items) ? items : []);
      })
      .catch(() => toast.error('Failed to load networks'))
      .finally(() => setLoading(false));
  }, [open, toast]);

  useEffect(() => {
    if (!open) return;
    const handler = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setOpen(false);
        setShowCreate(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const filtered = networks.filter((n) =>
    `${n.name} ${n.cidr ?? ''}`.toLowerCase().includes(search.toLowerCase())
  );

  const handleSelect = useCallback(
    (net) => {
      onChange({ id: net.id, name: net.name, cidr: net.cidr ?? undefined });
      setOpen(false);
      setSearch('');
      setShowCreate(false);
    },
    [onChange]
  );

  const handleClear = useCallback(
    (e) => {
      e.stopPropagation();
      onChange(null);
    },
    [onChange]
  );

  const handleCidrChange = useCallback((val) => {
    setNewCidr(val);
    if (val && !isValidCidr(val)) {
      setCidrError('Invalid CIDR (e.g. 192.168.1.0/24)');
    } else {
      setCidrError('');
    }
  }, []);

  const handleCreate = useCallback(async () => {
    if (!newName.trim()) return;
    if (newCidr && !isValidCidr(newCidr)) {
      setCidrError('Invalid CIDR (e.g. 192.168.1.0/24)');
      return;
    }
    setCreating(true);
    try {
      const payload = { name: newName.trim() };
      if (newCidr.trim()) payload.cidr = newCidr.trim();
      const res = await networksApi.create(payload);
      const net = res.data;
      onChange({ id: net.id, name: net.name, cidr: net.cidr ?? undefined });
      setOpen(false);
      setShowCreate(false);
      setNewName('');
      setNewCidr('');
    } catch {
      toast.error('Failed to create network');
    } finally {
      setCreating(false);
    }
  }, [newName, newCidr, onChange, toast]);

  if (value) {
    return (
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          background: 'rgba(56,189,248,0.12)',
          border: '1px solid rgba(56,189,248,0.35)',
          borderRadius: 6,
          padding: '4px 10px',
          fontSize: 11,
          color: '#38bdf8',
          fontFamily: 'monospace',
          whiteSpace: 'nowrap',
        }}
      >
        <span style={{ color: '#6b6b8a', fontSize: 10 }}>NETWORK</span>
        {value.name}
        {value.cidr && <span style={{ color: '#6b6b8a', fontSize: 10 }}>{value.cidr}</span>}
        {!disabled && (
          <button
            type="button"
            onClick={handleClear}
            style={{
              background: 'none',
              border: 'none',
              color: '#ef4444',
              cursor: 'pointer',
              padding: 0,
              lineHeight: 1,
              marginLeft: 2,
              fontSize: 13,
            }}
            title="Clear network"
            aria-label="Clear network"
          >
            ×
          </button>
        )}
      </div>
    );
  }

  return (
    <div ref={containerRef} style={{ position: 'relative' }}>
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
        style={{
          background: '#1e2a38',
          border: '1px solid rgba(56,189,248,0.4)',
          borderRadius: 6,
          color: '#38bdf8',
          fontSize: 11,
          padding: '4px 10px',
          fontFamily: 'monospace',
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          cursor: disabled ? 'not-allowed' : 'pointer',
          opacity: disabled ? 0.5 : 1,
          whiteSpace: 'nowrap',
        }}
      >
        <span style={{ color: '#6b6b8a', fontSize: 10 }}>NETWORK</span>
        Select… ▾
      </button>

      {open && (
        <div
          style={{
            position: 'absolute',
            top: 34,
            left: 0,
            minWidth: 260,
            background: 'var(--color-surface, #1a1a2e)',
            border: '1px solid var(--color-border, #3a3a5e)',
            borderRadius: 8,
            boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
            zIndex: 200,
            overflow: 'hidden',
          }}
        >
          <div
            style={{ padding: '8px 10px', borderBottom: '1px solid var(--color-border, #2a2a3e)' }}
          >
            <input
              className="cb-input"
              type="text"
              placeholder="Search networks…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              autoFocus
              style={{ width: '100%', boxSizing: 'border-box', fontSize: 11 }}
            />
          </div>

          <div style={{ maxHeight: 200, overflowY: 'auto' }}>
            {loading && (
              <div
                style={{
                  padding: '10px 12px',
                  fontSize: 11,
                  color: 'var(--color-text-muted, #6b6b8a)',
                }}
              >
                Loading…
              </div>
            )}
            {!loading && filtered.length === 0 && !showCreate && (
              <div
                style={{
                  padding: '10px 12px',
                  fontSize: 11,
                  color: 'var(--color-text-muted, #6b6b8a)',
                }}
              >
                No networks available. Create one below.
              </div>
            )}
            {filtered.map((net) => (
              <button
                key={net.id}
                type="button"
                onClick={() => handleSelect(net)}
                style={{
                  width: '100%',
                  textAlign: 'left',
                  background: 'none',
                  border: 'none',
                  borderBottom: '1px solid var(--color-border, #1e1e30)',
                  padding: '8px 12px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  cursor: 'pointer',
                  color: 'var(--color-text, #c0c0e0)',
                  fontSize: 11,
                  fontFamily: 'monospace',
                }}
                onMouseEnter={(e) =>
                  (e.currentTarget.style.background = 'var(--color-bg-alt, #2a2a3e)')
                }
                onMouseLeave={(e) => (e.currentTarget.style.background = 'none')}
              >
                <span style={{ flex: 1 }}>🌐 {net.name}</span>
                {net.cidr && (
                  <span style={{ color: 'var(--color-text-muted, #6b6b8a)', fontSize: 10 }}>
                    {net.cidr}
                  </span>
                )}
              </button>
            ))}
          </div>

          {!showCreate && (
            <button
              type="button"
              onClick={() => setShowCreate(true)}
              style={{
                width: '100%',
                textAlign: 'left',
                background: 'none',
                border: 'none',
                borderTop: '1px solid var(--color-border, #2a2a3e)',
                padding: '8px 12px',
                color: '#38bdf8',
                fontSize: 11,
                fontFamily: 'monospace',
                cursor: 'pointer',
              }}
            >
              ＋ Create new network…
            </button>
          )}

          {showCreate && (
            <div
              style={{
                padding: '10px 12px',
                background: 'rgba(56,189,248,0.04)',
                borderTop: '1px solid rgba(56,189,248,0.2)',
                display: 'flex',
                flexDirection: 'column',
                gap: 8,
              }}
            >
              <div style={{ fontSize: 10, color: '#38bdf8', fontWeight: 600 }}>New Network</div>
              <div>
                <div className="cb-label" style={{ fontSize: 10 }}>
                  Name *
                </div>
                <input
                  className="cb-input"
                  type="text"
                  placeholder="e.g., Prod Servers"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  style={{ width: '100%', boxSizing: 'border-box', fontSize: 11 }}
                />
              </div>
              <div>
                <div className="cb-label" style={{ fontSize: 10 }}>
                  CIDR (optional)
                </div>
                <input
                  className="cb-input"
                  type="text"
                  placeholder="e.g., 192.168.1.0/24"
                  value={newCidr}
                  onChange={(e) => handleCidrChange(e.target.value)}
                  style={{ width: '100%', boxSizing: 'border-box', fontSize: 11 }}
                />
                {cidrError && (
                  <div className="cb-hint" style={{ color: '#ef4444', fontSize: 10 }}>
                    {cidrError}
                  </div>
                )}
              </div>
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 6 }}>
                <button
                  type="button"
                  className="btn btn-secondary"
                  style={{ fontSize: 11 }}
                  onClick={() => {
                    setShowCreate(false);
                    setNewName('');
                    setNewCidr('');
                    setCidrError('');
                  }}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className="btn btn-primary"
                  style={{
                    fontSize: 11,
                    background: 'rgba(56,189,248,0.2)',
                    color: '#38bdf8',
                    border: '1px solid rgba(56,189,248,0.4)',
                  }}
                  onClick={handleCreate}
                  disabled={!newName.trim() || !!cidrError || creating}
                >
                  {creating ? 'Creating…' : 'Create & Select'}
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

NetworkSelectorDropdown.propTypes = {
  value: PropTypes.shape({
    id: PropTypes.number,
    name: PropTypes.string.isRequired,
    cidr: PropTypes.string,
  }),
  onChange: PropTypes.func.isRequired,
  disabled: PropTypes.bool,
};
