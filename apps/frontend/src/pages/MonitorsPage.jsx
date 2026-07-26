import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Activity } from 'lucide-react';
import {
  createMonitor,
  deleteMonitor,
  getMonitorEvents,
  listMonitors,
  pauseMonitor,
  resumeMonitor,
  updateMonitor,
} from '../api/monitor';
import { useMonitorStream } from '../hooks/useMonitorStream';
import EntityTable from '../components/EntityTable';
import ConfirmDialog from '../components/common/ConfirmDialog';
import { SkeletonTable } from '../components/common/SkeletonTable';
import { useToast } from '../components/common/Toast';
import CheckHistoryBar from '../components/monitors/CheckHistoryBar';
import MonitorForm from '../components/monitors/MonitorForm';
import StatusPill from '../components/monitors/StatusPill';

export default function MonitorsPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const [monitors, setMonitors] = useState([]);
  const [eventsById, setEventsById] = useState({});
  const [editing, setEditing] = useState(null); // null | 'new' | monitor object
  const [loading, setLoading] = useState(true);
  const [confirmState, setConfirmState] = useState({ open: false, message: '', onConfirm: null });

  const monitorIds = useMemo(() => monitors.map((m) => m.id), [monitors]);
  const { statuses } = useMonitorStream({ monitorIds });

  const refresh = useCallback(async () => {
    try {
      const { data } = await listMonitors();
      setMonitors(data);
      const entries = await Promise.all(
        data.map(async (m) => [m.id, (await getMonitorEvents(m.id, 40)).data])
      );
      setEventsById(Object.fromEntries(entries));
    } catch (err) {
      toast.error(err?.response?.data?.detail || 'Failed to load monitors');
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 60000); // REST safety net under the WS push
    return () => clearInterval(t);
  }, [refresh]);

  const liveStatus = useCallback((m) => statuses.get(m.id)?.status || m.status, [statuses]);

  const handleSubmit = async (form) => {
    if (editing === 'new') await createMonitor(form);
    else await updateMonitor(editing.id, form);
    setEditing(null);
    toast.success('Monitor saved.');
    await refresh();
  };

  const togglePause = async (m) => {
    try {
      await (m.enabled ? pauseMonitor(m.id) : resumeMonitor(m.id));
      await refresh();
    } catch (err) {
      toast.error(err?.response?.data?.detail || 'Failed to update monitor');
    }
  };

  const handleDelete = (m) => {
    setConfirmState({
      open: true,
      message: `Delete monitor "${m.name}"? This cannot be undone.`,
      onConfirm: async () => {
        try {
          await deleteMonitor(m.id);
          toast.success('Monitor deleted.');
          await refresh();
        } catch (err) {
          toast.error(err?.response?.data?.detail || 'Failed to delete monitor');
        } finally {
          setConfirmState((s) => ({ ...s, open: false }));
        }
      },
    });
  };

  const columns = useMemo(
    () => [
      {
        key: 'status',
        label: 'Status',
        render: (_, m) => <StatusPill status={liveStatus(m)} enabled={m.enabled} />,
      },
      { key: 'name', label: 'Name' },
      { key: 'check_type', label: 'Type', render: (v) => v.toUpperCase() },
      { key: 'target', label: 'Target', render: (_, m) => m.config?.url || m.host },
      {
        key: 'history',
        label: 'History',
        render: (_, m) => <CheckHistoryBar events={eventsById[m.id] || []} />,
      },
      {
        key: 'uptime_pct_24h',
        label: 'Uptime 24h',
        render: (v) => (v != null ? `${v}%` : '—'),
      },
      {
        key: 'latency_ms',
        label: 'Latency',
        render: (v) => (v != null ? `${Math.round(v)} ms` : '—'),
      },
      {
        key: 'pause',
        label: '',
        render: (_, m) => (
          <button
            className="btn"
            onClick={(e) => {
              e.stopPropagation();
              togglePause(m);
            }}
          >
            {m.enabled ? 'Pause' : 'Resume'}
          </button>
        ),
      },
    ],
    [eventsById, liveStatus] // eslint-disable-line react-hooks/exhaustive-deps
  );

  return (
    <div className="page">
      <div className="page-header">
        <div className="tw-flex tw-items-center tw-gap-3">
          <Activity className="tw-text-cb-primary" size={24} />
          <h2>Monitors</h2>
        </div>
        <button className="btn btn-primary" onClick={() => setEditing('new')}>
          + Add monitor
        </button>
      </div>

      {loading ? (
        <SkeletonTable cols={8} />
      ) : (
        <>
          <EntityTable
            columns={columns}
            data={monitors}
            onEdit={(row) => setEditing(row)}
            onDelete={(_id, row) => handleDelete(row || monitors.find((m) => m.id === _id))}
            onRowClick={(row) => navigate(`/monitors/${row.id}`)}
          />
          {monitors.length === 0 && (
            <p className="text-muted" style={{ marginTop: 12 }}>
              No monitors yet — add one to start watching a service.
            </p>
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
