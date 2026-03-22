/**
 * PublicStatusPage — unauthenticated public-facing status page.
 * Renders overall status, monitor groups, and recent incidents.
 * No auth headers; uses publicApi.fetchStatusPage(slug).
 * All colors use CSS custom properties so the page respects the active theme.
 */
import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { CheckCircle, AlertTriangle, XCircle, Clock, Radio } from 'lucide-react';
import { publicApi } from '../api/publicApi';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function timeAgo(isoString) {
  if (!isoString) return '—';
  const diff = Math.floor((Date.now() - new Date(isoString).getTime()) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return new Date(isoString).toLocaleDateString();
}

function duration(start, end) {
  if (!end) return 'ongoing';
  const diff = Math.floor((new Date(end).getTime() - new Date(start).getTime()) / 1000);
  const h = Math.floor(diff / 3600);
  const m = Math.floor((diff % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function formatDatetime(isoString) {
  if (!isoString) return '—';
  return new Date(isoString).toLocaleString();
}

// ---------------------------------------------------------------------------
// Status config — all colors via CSS variables
// ---------------------------------------------------------------------------

const STATUS_CONFIG = new Map([
  [
    'operational',
    {
      border: 'var(--color-success, #10b981)',
      icon: <CheckCircle size={28} color="var(--color-success, #10b981)" />,
      label: 'All Systems Operational',
      sub: 'All services running normally',
    },
  ],
  [
    'partial',
    {
      border: 'var(--color-primary)',
      icon: <AlertTriangle size={28} color="var(--color-primary)" />,
      label: 'Partial Outage',
      sub: null,
    },
  ],
  [
    'major',
    {
      border: 'var(--color-danger, #ef4444)',
      icon: <XCircle size={28} color="var(--color-danger, #ef4444)" />,
      label: 'Major Outage',
      sub: 'All services are down',
    },
  ],
  [
    'unknown',
    {
      border: 'var(--color-border)',
      icon: <Clock size={28} color="var(--color-text-muted)" />,
      label: 'No monitors configured',
      sub: '',
    },
  ],
]);

// Semantic status → CSS variable
const STATUS_COLOR = new Map([
  ['up', 'var(--color-success, #10b981)'],
  ['down', 'var(--color-danger, #ef4444)'],
  ['maintenance', 'var(--color-primary)'],
  ['pending', 'var(--color-text-muted)'],
]);

const STATUS_LABELS = new Map([
  ['up', 'UP'],
  ['down', 'DOWN'],
  ['maintenance', 'MAINTENANCE'],
  ['pending', 'PENDING'],
]);

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatusDot({ status }) {
  const color = STATUS_COLOR.get(status) || STATUS_COLOR.get('pending');
  const pulse = status === 'up';
  return (
    <span
      style={{
        display: 'inline-block',
        width: 9,
        height: 9,
        borderRadius: '50%',
        background: color,
        flexShrink: 0,
        animation: pulse ? 'pulse-dot 1.8s ease-in-out infinite' : 'none',
      }}
    />
  );
}

function StatusPill({ status }) {
  const color = STATUS_COLOR.get(status) || STATUS_COLOR.get('pending');
  const label = STATUS_LABELS.get(status) ?? 'PENDING';
  return (
    <span
      style={{
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: '0.08em',
        padding: '2px 8px',
        borderRadius: 4,
        background: `color-mix(in srgb, ${color} 15%, var(--color-surface))`,
        color,
        border: `1px solid color-mix(in srgb, ${color} 35%, transparent)`,
      }}
    >
      {label}
    </span>
  );
}

function UptimeValue({ value }) {
  if (value === null || value === undefined)
    return <span style={{ color: 'var(--color-text-muted)' }}>—</span>;
  const pct = typeof value === 'number' ? value.toFixed(2) : value;
  const color = parseFloat(pct) >= 99 ? 'var(--color-success, #10b981)' : 'var(--color-primary)';
  return <span style={{ color, fontWeight: 600 }}>{pct}%</span>;
}

function StatBox({ label, children }) {
  return (
    <div
      style={{
        background: 'var(--color-bg)',
        border: '1px solid var(--color-border)',
        borderRadius: 6,
        padding: '6px 12px',
        minWidth: 110,
        display: 'flex',
        flexDirection: 'column',
        gap: 2,
      }}
    >
      <span
        style={{
          fontSize: 10,
          color: 'var(--color-text-muted)',
          letterSpacing: '0.06em',
          textTransform: 'uppercase',
        }}
      >
        {label}
      </span>
      <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--color-text)' }}>{children}</span>
    </div>
  );
}

function IntegrationBadge({ name }) {
  if (!name) return null;
  return (
    <span
      style={{
        fontSize: 10,
        fontWeight: 600,
        padding: '2px 7px',
        borderRadius: 4,
        background: 'rgba(var(--color-primary-rgb), 0.15)',
        color: 'var(--color-primary)',
        border: '1px solid rgba(var(--color-primary-rgb), 0.3)',
        letterSpacing: '0.05em',
      }}
    >
      {name}
    </span>
  );
}

function MonitorCard({ monitor }) {
  return (
    <div
      style={{
        background: 'var(--color-surface)',
        border: '1px solid var(--color-border)',
        borderRadius: 8,
        padding: '12px 16px',
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <StatusDot status={monitor.status} />
        <span
          style={{
            fontWeight: 600,
            fontSize: 14,
            color: 'var(--color-text)',
            flex: 1,
            minWidth: 100,
          }}
        >
          {monitor.name}
        </span>
        <IntegrationBadge name={monitor.integration_name} />
        <StatusPill status={monitor.status} />
      </div>

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <StatBox label="7d Uptime">
          <UptimeValue value={monitor.uptime_7d} />
        </StatBox>
        <StatBox label="30d Uptime">
          <UptimeValue value={monitor.uptime_30d} />
        </StatBox>
        <StatBox label="Last Checked">
          <span style={{ color: 'var(--color-text)', fontSize: 13 }}>
            {timeAgo(monitor.last_checked_at)}
          </span>
        </StatBox>
      </div>

      {monitor.url && (
        <div style={{ fontSize: 11, color: 'var(--color-text-muted)', wordBreak: 'break-all' }}>
          {monitor.url}
        </div>
      )}
    </div>
  );
}

function GroupSection({ group }) {
  const count = group.monitors?.length ?? 0;
  return (
    <div style={{ marginBottom: 32 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
        <span
          style={{
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: '0.12em',
            textTransform: 'uppercase',
            color: 'var(--color-text-muted)',
          }}
        >
          {group.name}
        </span>
        <span
          style={{
            fontSize: 10,
            fontWeight: 600,
            padding: '1px 7px',
            borderRadius: 10,
            background: 'var(--color-secondary)',
            color: 'var(--color-text-muted)',
          }}
        >
          {count}
        </span>
        <div style={{ flex: 1, height: 1, background: 'var(--color-border)' }} />
      </div>

      {count === 0 ? (
        <p style={{ fontSize: 13, color: 'var(--color-text-muted)', paddingLeft: 4 }}>
          No monitors in this group.
        </p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {group.monitors.map((m) => (
            <MonitorCard key={m.id} monitor={m} />
          ))}
        </div>
      )}
    </div>
  );
}

function IncidentCard({ incident }) {
  const resolved = !!incident.resolved_at;
  const borderColor = resolved ? 'var(--color-success, #10b981)' : 'var(--color-danger, #ef4444)';
  const statusLabel = resolved ? 'RESOLVED' : 'ONGOING';

  return (
    <div
      style={{
        borderLeft: `3px solid ${borderColor}`,
        background: 'var(--color-surface)',
        border: `1px solid var(--color-border)`,
        borderLeftColor: borderColor,
        borderRadius: 8,
        padding: '12px 16px',
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span style={{ fontWeight: 600, fontSize: 13, color: 'var(--color-text)' }}>
          {incident.monitor_name}
        </span>
        <IntegrationBadge name={incident.integration_name} />
        <span
          style={{
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: '0.08em',
            color: borderColor,
            background: `color-mix(in srgb, ${borderColor} 15%, var(--color-surface))`,
            border: `1px solid color-mix(in srgb, ${borderColor} 35%, transparent)`,
            borderRadius: 4,
            padding: '2px 7px',
          }}
        >
          {statusLabel}
        </span>
      </div>
      <div
        style={{
          fontSize: 12,
          color: 'var(--color-text-muted)',
          display: 'flex',
          gap: 16,
          flexWrap: 'wrap',
        }}
      >
        <span>Started: {formatDatetime(incident.detected_at)}</span>
        <span>Duration: {duration(incident.detected_at, incident.resolved_at)}</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Loading skeleton
// ---------------------------------------------------------------------------

function Skeleton() {
  return (
    <div style={{ padding: '40px 24px', maxWidth: 800, margin: '0 auto' }}>
      {[1, 2, 3].map((i) => (
        <div
          key={i}
          style={{
            height: 72,
            background: 'var(--color-surface)',
            borderRadius: 8,
            marginBottom: 12,
            animation: 'skeleton-pulse 1.4s ease-in-out infinite',
          }}
        />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function PublicStatusPage() {
  const { slug } = useParams();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [errorState, setErrorState] = useState(null); // null | 403 | 404 | 'error'

  useEffect(() => {
    if (!slug) return;
    const controller = new AbortController();
    setLoading(true);
    setErrorState(null);
    publicApi
      .fetchStatusPage(slug, controller.signal)
      .then((res) => {
        if (!controller.signal.aborted) {
          setData(res.data);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        const status = err?.response?.status;
        if (status === 403) setErrorState(403);
        else if (status === 404) setErrorState(404);
        else setErrorState('error');
        setLoading(false);
      });
    return () => controller.abort();
  }, [slug]);

  const affectedCount =
    data?.groups?.reduce(
      (acc, g) => acc + (g.monitors?.filter((m) => m.status === 'down').length ?? 0),
      0
    ) ?? 0;
  const totalCount = data?.groups?.reduce((acc, g) => acc + (g.monitors?.length ?? 0), 0) ?? 0;

  const overallStatus = data?.overall_status ?? 'unknown';
  const statusCfg = STATUS_CONFIG.get(overallStatus) ?? STATUS_CONFIG.get('unknown');
  const navDotColor =
    STATUS_COLOR.get(
      overallStatus === 'operational' ? 'up' : overallStatus === 'major' ? 'down' : 'maintenance'
    ) ?? STATUS_COLOR.get('pending');

  const incidents = data?.incidents ?? [];

  return (
    <>
      <style>{`
        @keyframes pulse-dot {
          0%   { box-shadow: 0 0 0 0 var(--color-success, #10b981); }
          70%  { box-shadow: 0 0 0 6px transparent; }
          100% { box-shadow: 0 0 0 0 transparent; }
        }
        @keyframes skeleton-pulse {
          0%, 100% { opacity: 0.5; }
          50%       { opacity: 1; }
        }
        * { box-sizing: border-box; }
        body { margin: 0; }
      `}</style>

      <div
        style={{
          minHeight: '100vh',
          background: 'var(--color-bg)',
          color: 'var(--color-text)',
          fontFamily: 'var(--font)',
        }}
      >
        {/* Nav bar */}
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            height: 52,
            background: 'var(--color-bg)',
            backdropFilter: 'blur(8px)',
            borderBottom: '1px solid var(--color-border)',
            display: 'flex',
            alignItems: 'center',
            padding: '0 24px',
            zIndex: 100,
            gap: 10,
          }}
        >
          <span
            style={{
              width: 10,
              height: 10,
              borderRadius: '50%',
              background: navDotColor,
              flexShrink: 0,
              animation:
                overallStatus === 'operational' ? 'pulse-dot 1.8s ease-in-out infinite' : 'none',
            }}
          />
          <span style={{ fontWeight: 700, fontSize: 15, flex: 1, color: 'var(--color-text)' }}>
            {data?.title ?? slug}
          </span>
          {data?.updated_at && (
            <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
              Last updated {timeAgo(data.updated_at)}
            </span>
          )}
        </div>

        {/* Page content — padded below fixed nav */}
        <div style={{ paddingTop: 52 }}>
          {loading ? (
            <Skeleton />
          ) : errorState === 403 ? (
            <ErrorPlaceholder
              icon={<XCircle size={40} color="var(--color-text-muted)" />}
              title="This page is private"
              sub="You don't have permission to view this status page."
            />
          ) : errorState === 404 ? (
            <ErrorPlaceholder
              icon={<Radio size={40} color="var(--color-text-muted)" />}
              title="Status page not found"
              sub={`No status page exists for slug "${slug}".`}
            />
          ) : errorState ? (
            <ErrorPlaceholder
              icon={<AlertTriangle size={40} color="var(--color-primary)" />}
              title="Something went wrong"
              sub="Unable to load this status page. Please try again later."
            />
          ) : (
            <>
              {/* Overall status banner */}
              <div
                style={{
                  background: 'var(--color-surface)',
                  borderBottom: `3px solid ${statusCfg.border}`,
                  padding: '28px 24px',
                  textAlign: 'center',
                }}
              >
                <div style={{ display: 'inline-flex', alignItems: 'center', gap: 12 }}>
                  {statusCfg.icon}
                  <div style={{ textAlign: 'left' }}>
                    <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--color-text)' }}>
                      {statusCfg.label}
                    </div>
                    <div style={{ fontSize: 13, color: 'var(--color-text-muted)', marginTop: 2 }}>
                      {overallStatus === 'partial'
                        ? `${affectedCount} of ${totalCount} services affected`
                        : statusCfg.sub}
                    </div>
                  </div>
                </div>
              </div>

              {/* Groups */}
              <div style={{ maxWidth: 820, margin: '0 auto', padding: '32px 24px 0' }}>
                {(data?.groups ?? []).map((group) => (
                  <GroupSection key={group.id} group={group} />
                ))}
              </div>

              {/* Recent Incidents */}
              <div style={{ maxWidth: 820, margin: '0 auto', padding: '16px 24px 48px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
                  <span
                    style={{
                      fontSize: 11,
                      fontWeight: 700,
                      letterSpacing: '0.12em',
                      textTransform: 'uppercase',
                      color: 'var(--color-text-muted)',
                    }}
                  >
                    Recent Incidents
                  </span>
                  <div style={{ flex: 1, height: 1, background: 'var(--color-border)' }} />
                </div>

                {incidents.length === 0 ? (
                  <p style={{ fontSize: 13, color: 'var(--color-text-muted)', paddingLeft: 4 }}>
                    No incidents in the last 30 days.
                  </p>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                    {incidents.map((inc) => (
                      <IncidentCard key={`${inc.monitor_name}-${inc.detected_at}`} incident={inc} />
                    ))}
                  </div>
                )}
              </div>
            </>
          )}
        </div>

        {/* Footer */}
        <div
          style={{
            textAlign: 'center',
            padding: '20px 24px',
            fontSize: 12,
            color: 'var(--color-text-muted)',
            borderTop: '1px solid var(--color-border)',
          }}
        >
          Powered by Circuit Breaker
        </div>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Error placeholder
// ---------------------------------------------------------------------------

function ErrorPlaceholder({ icon, title, sub }) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: 'calc(100vh - 52px)',
        gap: 14,
        color: 'var(--color-text-muted)',
        padding: 24,
        textAlign: 'center',
      }}
    >
      {icon}
      <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--color-text)' }}>{title}</div>
      <div style={{ fontSize: 13, maxWidth: 360 }}>{sub}</div>
    </div>
  );
}
