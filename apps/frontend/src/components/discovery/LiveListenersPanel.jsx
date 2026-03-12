/* eslint-disable security/detect-object-injection -- internal key lookups */
import React, { useState, useEffect, useCallback } from 'react';
import { Radio, X } from 'lucide-react';
import { getListenerEvents, getListenerStatus } from '../../api/discovery.js';

const POLL_INTERVAL_MS = 10_000;

const SOURCE_COLORS = { mdns: '#06b6d4', ssdp: '#a78bfa' };

function SourceBadge({ source }) {
  const color = SOURCE_COLORS[source] || '#6b7280';
  return (
    <span
      style={{
        background: `${color}22`,
        color,
        border: `1px solid ${color}44`,
        borderRadius: 4,
        fontSize: 9,
        padding: '1px 5px',
        fontFamily: 'monospace',
        textTransform: 'uppercase',
        letterSpacing: '0.04em',
      }}
    >
      {source}
    </span>
  );
}

function timeAgo(isoStr) {
  if (!isoStr) return '—';
  const diffSecs = Math.floor((Date.now() - new Date(isoStr).getTime()) / 1000);
  if (diffSecs < 60) return `${diffSecs}s ago`;
  if (diffSecs < 3600) return `${Math.floor(diffSecs / 60)}m ago`;
  return `${Math.floor(diffSecs / 3600)}h ago`;
}

export default function LiveListenersPanel({ listenerEnabled = false }) {
  const [status, setStatus] = useState({ running: false, mdns_active: false, ssdp_active: false });
  const [events, setEvents] = useState([]);
  const [collapsed, setCollapsed] = useState(false);

  const fetchStatus = useCallback(async () => {
    try {
      const r = await getListenerStatus();
      setStatus((prev) => r.data ?? prev);
    } catch {
      // network error — keep last known status
    }
  }, []);

  const fetchEvents = useCallback(async () => {
    try {
      const r = await getListenerEvents({ limit: 50 });
      setEvents(Array.isArray(r.data) ? r.data : []);
    } catch {
      // network error — keep last known events
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    fetchEvents();
    const id = setInterval(() => {
      fetchStatus();
      fetchEvents();
    }, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [fetchStatus, fetchEvents]);

  const isActive = status.running && listenerEnabled;

  return (
    <div className="live-listeners-panel" style={{ marginTop: 12 }}>
      {/* Header */}
      <button
        type="button"
        className="listeners-header"
        onClick={() => setCollapsed((c) => !c)}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          width: '100%',
          background: 'none',
          border: 'none',
          cursor: 'pointer',
          padding: '4px 0',
          color: 'var(--color-text)',
        }}
      >
        <Radio size={13} style={{ color: isActive ? '#22c55e' : '#6b7280', flexShrink: 0 }} />
        <span style={{ fontSize: 11, fontWeight: 600, flex: 1, textAlign: 'left' }}>
          Live Listeners
        </span>
        {isActive ? (
          <span
            style={{
              fontSize: 9,
              color: '#22c55e',
              fontFamily: 'monospace',
              background: '#22c55e18',
              border: '1px solid #22c55e44',
              borderRadius: 4,
              padding: '1px 5px',
            }}
          >
            {[status.mdns_active && 'mDNS', status.ssdp_active && 'SSDP']
              .filter(Boolean)
              .join(' · ')}
          </span>
        ) : (
          <span style={{ fontSize: 9, color: '#6b7280', fontFamily: 'monospace' }}>off</span>
        )}
        <span style={{ fontSize: 10, color: 'var(--color-text-muted)', marginLeft: 4 }}>
          {collapsed ? '▸' : '▾'}
        </span>
      </button>

      {!collapsed && (
        <>
          {/* Event list */}
          {events.length === 0 ? (
            <div
              style={{
                fontSize: 10,
                color: 'var(--color-text-muted)',
                padding: '6px 0',
                fontStyle: 'italic',
              }}
            >
              {listenerEnabled
                ? 'No events captured yet'
                : 'Enable the listener in Settings → Discovery to start capturing'}
            </div>
          ) : (
            <>
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'flex-end',
                  marginBottom: 4,
                }}
              >
                <button
                  type="button"
                  title="Clear local event list"
                  onClick={() => setEvents([])}
                  style={{
                    background: 'none',
                    border: 'none',
                    cursor: 'pointer',
                    color: 'var(--color-text-muted)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 3,
                    fontSize: 9,
                    padding: 0,
                  }}
                >
                  <X size={10} /> Clear
                </button>
              </div>
              <div style={{ maxHeight: 200, overflowY: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10 }}>
                  <thead>
                    <tr
                      style={{
                        color: 'var(--color-text-muted)',
                        borderBottom: '1px solid var(--color-border)',
                      }}
                    >
                      <th style={{ textAlign: 'left', padding: '2px 4px', fontWeight: 600 }}>
                        Src
                      </th>
                      <th style={{ textAlign: 'left', padding: '2px 4px', fontWeight: 600 }}>IP</th>
                      <th style={{ textAlign: 'left', padding: '2px 4px', fontWeight: 600 }}>
                        Name
                      </th>
                      <th style={{ textAlign: 'left', padding: '2px 4px', fontWeight: 600 }}>
                        Port
                      </th>
                      <th style={{ textAlign: 'right', padding: '2px 4px', fontWeight: 600 }}>
                        When
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {events.map((e) => (
                      <tr key={e.id} style={{ borderBottom: '1px solid var(--color-border)' }}>
                        <td style={{ padding: '3px 4px' }}>
                          <SourceBadge source={e.source} />
                        </td>
                        <td
                          style={{
                            padding: '3px 4px',
                            fontFamily: 'monospace',
                            color: 'var(--color-primary)',
                          }}
                        >
                          {e.ip_address || '—'}
                        </td>
                        <td
                          style={{
                            padding: '3px 4px',
                            maxWidth: 100,
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                          }}
                          title={e.name || undefined}
                        >
                          {e.name || e.service_type || '—'}
                        </td>
                        <td style={{ padding: '3px 4px', fontFamily: 'monospace' }}>
                          {e.port || '—'}
                        </td>
                        <td
                          style={{
                            padding: '3px 4px',
                            textAlign: 'right',
                            color: 'var(--color-text-muted)',
                          }}
                        >
                          {timeAgo(e.seen_at)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}
