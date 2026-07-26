/* eslint-disable security/detect-object-injection -- keys are monitor ids and our own status strings */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Activity } from 'lucide-react';
import {
  createMonitor,
  deleteMonitor,
  getMonitorEvents,
  getMonitorHistory,
  getMonitorsOverview,
  pauseMonitor,
  resumeMonitor,
  runCheck,
  updateMonitor,
} from '../api/monitor';
import { useMonitorStream } from '../hooks/useMonitorStream';
import ConfirmDialog from '../components/common/ConfirmDialog';
import { useToast } from '../components/common/Toast';
import MonitorForm from '../components/monitors/MonitorForm';
import MonitorFilterBar, { SORT_OPTIONS } from '../components/monitors/MonitorFilterBar';
import MonitorGroup from '../components/monitors/MonitorGroup';
import MonitorSummaryStrip from '../components/monitors/MonitorSummaryStrip';
import { groupStatusOf } from '../components/monitors/MonitorCard';
import { formatAgo } from '../components/monitors/monitorFormat';
import '../styles/monitors.css';

const GROUP_ORDER = ['down', 'pending', 'maintenance', 'up', 'paused'];
const REFRESH_MS = 60000;
const SERIES_MAX = 12;
const CHECKS_MAX = 20;
const SORT_VALUES = SORT_OPTIONS.map((o) => o.value);

function groupRank(status) {
  const i = GROUP_ORDER.indexOf(status);
  return i === -1 ? GROUP_ORDER.length : i;
}

function sortMonitors(monitors, sort) {
  const byName = (a, b) => a.name.localeCompare(b.name);
  const nullsLast = (v) => (v == null ? Number.POSITIVE_INFINITY : v);
  const copy = [...monitors];
  switch (sort) {
    case 'name':
      return copy.sort(byName);
    case 'latency':
      return copy.sort((a, b) => nullsLast(b.latency_ms) - nullsLast(a.latency_ms) || byName(a, b));
    case 'uptime':
    case 'worst':
    default:
      return copy.sort(
        (a, b) => nullsLast(a.uptime_pct_24h) - nullsLast(b.uptime_pct_24h) || byName(a, b)
      );
  }
}

export default function MonitorsPage() {
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const [monitors, setMonitors] = useState([]);
  const [loading, setLoading] = useState(true);
  const [expandedIds, setExpandedIds] = useState(() => new Set());
  const [detailsById, setDetailsById] = useState({});
  const [busyId, setBusyId] = useState(null);
  const [editing, setEditing] = useState(null); // null | 'new' | monitor
  const [confirmState, setConfirmState] = useState({ open: false, message: '', onConfirm: null });
  const [now, setNow] = useState(() => Date.now());

  const statusFilter = params.get('status');
  const typeFilter = params.get('type');
  const q = params.get('q') || '';
  const sort = SORT_VALUES.includes(params.get('sort')) ? params.get('sort') : 'worst';

  const setParam = useCallback(
    (key, value) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (value) next.set(key, value);
          else next.delete(key);
          return next;
        },
        { replace: true }
      );
    },
    [setParams]
  );

  const refresh = useCallback(async () => {
    try {
      const { data } = await getMonitorsOverview();
      setMonitors(data);
    } catch (err) {
      toast.error(err?.response?.data?.detail || 'Failed to load monitors');
    } finally {
      setLoading(false);
    }
  }, [toast]);

  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;

  useEffect(() => {
    refreshRef.current();
    const t = setInterval(() => refreshRef.current(), REFRESH_MS); // safety net under the WS push
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000); // the header's last-check ticker
    return () => clearInterval(t);
  }, []);

  const monitorIds = useMemo(() => monitors.map((m) => m.id), [monitors]);
  const { statuses } = useMonitorStream({ monitorIds });

  // Fold live pushes onto the fetched rows: status, last check, and both series.
  const live = useMemo(() => {
    if (statuses.size === 0) return monitors;
    return monitors.map((m) => {
      const push = statuses.get(m.id);
      if (!push) return m;
      const check = {
        id: `live-${push.ts}`,
        status_to: push.status,
        msg: push.msg || '',
        created_at: push.ts,
      };
      const alreadyLogged = (m.recent_checks || [])[0]?.created_at === push.ts;
      return {
        ...m,
        status: push.status,
        last_polled_at: push.ts || m.last_polled_at,
        recent_checks: alreadyLogged
          ? m.recent_checks
          : [check, ...(m.recent_checks || [])].slice(0, CHECKS_MAX),
        latency_series:
          push.latency_ms != null
            ? [...(m.latency_series || []), push.latency_ms].slice(-SERIES_MAX)
            : m.latency_series,
      };
    });
  }, [monitors, statuses]);

  const counts = useMemo(() => {
    const acc = { total: live.length, up: 0, down: 0, pending: 0, paused: 0, maintenance: 0 };
    for (const m of live) {
      const status = groupStatusOf(m);
      if (Object.hasOwn(acc, status)) acc[status] += 1;
    }
    return acc;
  }, [live]);

  const typeCounts = useMemo(() => {
    const acc = {};
    for (const m of live) acc[m.check_type] = (acc[m.check_type] || 0) + 1;
    return acc;
  }, [live]);

  const visible = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return live.filter((m) => {
      if (statusFilter && groupStatusOf(m) !== statusFilter) return false;
      if (typeFilter && m.check_type !== typeFilter) return false;
      if (!needle) return true;
      return `${m.name} ${m.host} ${m.config?.url || ''}`.toLowerCase().includes(needle);
    });
  }, [live, statusFilter, typeFilter, q]);

  const groups = useMemo(() => {
    const byStatus = {};
    for (const m of visible) {
      const status = groupStatusOf(m);
      (byStatus[status] = byStatus[status] || []).push(m);
    }
    return Object.entries(byStatus)
      .map(([status, list]) => [status, sortMonitors(list, sort)])
      .sort((a, b) => groupRank(a[0]) - groupRank(b[0]));
  }, [visible, sort]);

  const lastCheck = useMemo(() => {
    const times = live.map((m) => m.last_polled_at).filter(Boolean);
    return times.length ? times.reduce((a, b) => (a > b ? a : b)) : null;
  }, [live]);

  const loadDetail = useCallback(async (monitorId) => {
    setDetailsById((prev) => ({
      ...prev,
      [monitorId]: { history: [], events: [], loading: true },
    }));
    try {
      const [hist, ev] = await Promise.all([
        getMonitorHistory(monitorId, { hours: 24 }),
        getMonitorEvents(monitorId, 40),
      ]);
      setDetailsById((prev) => ({
        ...prev,
        [monitorId]: { history: hist.data, events: ev.data, loading: false },
      }));
    } catch {
      setDetailsById((prev) => ({
        ...prev,
        [monitorId]: { history: [], events: [], loading: false },
      }));
    }
  }, []);

  const handleToggle = useCallback(
    (monitorId) => {
      setExpandedIds((prev) => {
        const next = new Set(prev);
        if (next.has(monitorId)) next.delete(monitorId);
        else next.add(monitorId);
        return next;
      });
      setDetailsById((prev) => {
        if (!prev[monitorId]) loadDetail(monitorId);
        return prev;
      });
    },
    [loadDetail]
  );

  const runAction = useCallback(
    async (monitor, fn, successMsg, { reloadDetail = false } = {}) => {
      setBusyId(monitor.id);
      try {
        await fn();
        toast.success(successMsg);
        await refreshRef.current();
        if (reloadDetail && expandedIds.has(monitor.id)) await loadDetail(monitor.id);
      } catch (err) {
        toast.error(err?.response?.data?.detail || 'Failed to update monitor');
      } finally {
        setBusyId(null);
      }
    },
    [expandedIds, loadDetail, toast]
  );

  const handleCheckNow = useCallback(
    (m) => runAction(m, () => runCheck(m.id), 'Probe triggered.', { reloadDetail: true }),
    [runAction]
  );
  const handlePause = useCallback(
    (m) =>
      runAction(
        m,
        () => (m.enabled ? pauseMonitor(m.id) : resumeMonitor(m.id)),
        m.enabled ? 'Monitoring paused.' : 'Monitoring resumed.'
      ),
    [runAction]
  );
  const handleEdit = useCallback((m) => setEditing(m), []);
  const handleDelete = useCallback(
    (m) =>
      setConfirmState({
        open: true,
        message: `Delete monitor "${m.name}"? This cannot be undone.`,
        onConfirm: async () => {
          setConfirmState((s) => ({ ...s, open: false }));
          await runAction(m, () => deleteMonitor(m.id), 'Monitor deleted.');
        },
      }),
    [runAction]
  );

  const handleSubmit = async (form) => {
    if (editing === 'new') await createMonitor(form);
    else await updateMonitor(editing.id, form);
    setEditing(null);
    toast.success('Monitor saved.');
    await refreshRef.current();
  };

  const clearFilters = () =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        ['status', 'type', 'q'].forEach((k) => next.delete(k));
        return next;
      },
      { replace: true }
    );

  const filtersActive = Boolean(statusFilter || typeFilter || q);

  return (
    <div className="page">
      <div className="page-header">
        <div className="tw-flex tw-items-center tw-gap-3">
          <Activity className="tw-text-cb-primary" size={24} />
          <h2>Monitors</h2>
          {lastCheck && <span className="mon-uptime">last check {formatAgo(lastCheck, now)}</span>}
        </div>
        <button className="btn btn-primary" onClick={() => setEditing('new')}>
          + Add monitor
        </button>
      </div>

      {loading ? (
        <div className="mon-wall">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="mon-skeleton" />
          ))}
        </div>
      ) : monitors.length === 0 ? (
        <div className="mon-empty">
          <p>No monitors yet — add one to start watching a host, service or URL.</p>
          <p className="text-muted" style={{ fontSize: '0.8rem', marginTop: 6 }}>
            You can also switch monitoring on for anything already in your inventory from the
            Hardware, Compute, Services and External pages.
          </p>
          <button
            className="btn btn-primary"
            style={{ marginTop: 12 }}
            onClick={() => setEditing('new')}
          >
            + Add monitor
          </button>
        </div>
      ) : (
        <>
          <MonitorSummaryStrip
            counts={counts}
            active={statusFilter}
            onSelect={(status) => setParam('status', status)}
          />
          <MonitorFilterBar
            q={q}
            onQ={(value) => setParam('q', value)}
            type={typeFilter}
            onType={(value) => setParam('type', value)}
            typeCounts={typeCounts}
            sort={sort}
            onSort={(value) => setParam('sort', value === 'worst' ? null : value)}
          />

          {visible.length === 0 ? (
            <div className="mon-empty">
              <p>No monitors match.</p>
              <button className="btn" style={{ marginTop: 12 }} onClick={clearFilters}>
                Clear filters
              </button>
            </div>
          ) : (
            <>
              {groups.map(([status, list]) => (
                <MonitorGroup
                  key={status}
                  status={status}
                  monitors={list}
                  expandedIds={expandedIds}
                  detailsById={detailsById}
                  busyId={busyId}
                  onToggle={handleToggle}
                  onCheckNow={handleCheckNow}
                  onPause={handlePause}
                  onEdit={handleEdit}
                  onDelete={handleDelete}
                />
              ))}
              {filtersActive && (
                <p className="text-muted" style={{ marginTop: 14, fontSize: '0.72rem' }}>
                  Showing {visible.length} of {monitors.length} monitors{' '}
                  <button className="btn btn-sm" onClick={clearFilters}>
                    Clear filters
                  </button>
                </p>
              )}
            </>
          )}
        </>
      )}

      {editing && (
        <MonitorForm
          initial={editing === 'new' ? null : editing}
          onSubmit={handleSubmit}
          onCancel={() => setEditing(null)}
        />
      )}

      <ConfirmDialog
        open={confirmState.open}
        message={confirmState.message}
        onConfirm={confirmState.onConfirm}
        onCancel={() => setConfirmState((s) => ({ ...s, open: false }))}
      />
    </div>
  );
}
