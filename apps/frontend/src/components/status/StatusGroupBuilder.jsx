/**
 * StatusGroupBuilder — right-panel group management for the selected status page.
 * Lists groups, allows adding / deleting, and shows a v2 dashboard summary.
 * ≤ 150 LOC, cognitive complexity ≤ 20.
 */
import React, { useEffect, useState } from 'react';
import PropTypes from 'prop-types';
import { Radio } from 'lucide-react';
import FormModal from '../common/FormModal';
import ConfirmDialog from '../common/ConfirmDialog';
import { SkeletonTable } from '../common/SkeletonTable';
import { integrationsApi } from '../../api/integrations.js';

const STATUS_COLOR = new Map([
  ['up', '#22c55e'],
  ['degraded', '#f59e0b'],
  ['down', '#ef4444'],
  ['unknown', 'var(--color-text-muted)'],
]);

const MONITOR_STATUS_COLOR = {
  up: '#22c55e',
  down: '#ef4444',
  pending: '#94a3b8',
  maintenance: '#f59e0b',
};

function GroupRow({ group, onDelete }) {
  const s = group.overall_status ?? 'unknown';
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '8px 0',
        borderBottom: '1px solid var(--color-border)',
      }}
    >
      <span
        style={{
          width: 8,
          height: 8,
          borderRadius: '50%',
          background: STATUS_COLOR.get(s) ?? 'grey',
          flexShrink: 0,
        }}
      />
      <span style={{ flex: 1, fontSize: 13 }}>{group.name}</span>
      <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
        {group.entity_count ?? 0} entities
      </span>
      <button
        className="btn btn-danger"
        style={{ fontSize: 11, padding: '2px 8px' }}
        onClick={() => onDelete(group.id)}
      >
        Remove
      </button>
    </div>
  );
}

GroupRow.propTypes = {
  group: PropTypes.object.isRequired,
  onDelete: PropTypes.func.isRequired,
};

function MonitorPickerSection({ monitors, groupNodes, onAddMonitorNode }) {
  const existing = new Set(
    (groupNodes || []).filter((n) => n.type === 'integration_monitor').map((n) => n.id)
  );
  const available = monitors.filter((m) => !existing.has(m.id));
  if (monitors.length === 0) return null;
  return (
    <div style={{ marginTop: 16 }}>
      <span
        style={{
          fontSize: 12,
          fontWeight: 600,
          color: 'var(--color-text-muted)',
          display: 'block',
          marginBottom: 6,
        }}
      >
        Monitors
      </span>
      {available.length === 0 ? (
        <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: 0 }}>
          All monitors added.
        </p>
      ) : (
        available.map((m) => (
          <div
            key={m.id}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              padding: '5px 0',
              borderBottom: '1px solid var(--color-border)',
              cursor: 'pointer',
            }}
            onClick={() => onAddMonitorNode({ type: 'integration_monitor', id: m.id })}
            title="Click to add to group"
          >
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: '50%',
                background: MONITOR_STATUS_COLOR[m.status] || '#94a3b8',
                flexShrink: 0,
              }}
            />
            {m.integration_name && (
              <span
                style={{
                  fontSize: 11,
                  fontWeight: 600,
                  padding: '1px 6px',
                  borderRadius: 10,
                  background: 'var(--color-surface-raised, rgba(255,255,255,0.07))',
                  border: '1px solid var(--color-border)',
                  color: 'var(--color-text-muted)',
                  flexShrink: 0,
                  whiteSpace: 'nowrap',
                }}
              >
                {m.integration_name}
              </span>
            )}
            <span style={{ fontSize: 13, flex: 1 }}>{m.name}</span>
            {m.uptime_7d != null && (
              <span style={{ fontSize: 11, color: 'var(--color-text-muted)', flexShrink: 0 }}>
                {m.uptime_7d.toFixed(1)}%
              </span>
            )}
            <span style={{ fontSize: 11, color: 'var(--color-primary, #6366f1)', flexShrink: 0 }}>
              + Add
            </span>
          </div>
        ))
      )}
    </div>
  );
}

MonitorPickerSection.propTypes = {
  monitors: PropTypes.array.isRequired,
  groupNodes: PropTypes.array,
  onAddMonitorNode: PropTypes.func.isRequired,
};

function MonitorNodeRow({ nodeId, monitors }) {
  const monitor = monitors.find((m) => m.id === nodeId);
  const name = monitor ? monitor.name : `Monitor #${nodeId}`;
  const color = monitor ? MONITOR_STATUS_COLOR[monitor.status] || '#94a3b8' : '#94a3b8';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0', fontSize: 12 }}>
      <span
        style={{
          width: 8,
          height: 8,
          borderRadius: '50%',
          background: color,
          flexShrink: 0,
        }}
      />
      <Radio size={12} style={{ flexShrink: 0 }} />
      <span style={{ flex: 1 }}>{name}</span>
      {monitor?.avg_response_ms != null && (
        <span style={{ fontSize: 11, color: 'var(--color-text-muted)', flexShrink: 0 }}>
          {Math.round(monitor.avg_response_ms)}ms
        </span>
      )}
      {monitor?.uptime_7d != null && (
        <span style={{ fontSize: 11, color: 'var(--color-text-muted)', flexShrink: 0 }}>
          {monitor.uptime_7d.toFixed(1)}%
        </span>
      )}
    </div>
  );
}

MonitorNodeRow.propTypes = {
  nodeId: PropTypes.oneOfType([PropTypes.string, PropTypes.number]).isRequired,
  monitors: PropTypes.array.isRequired,
};

const ADD_FIELDS = [{ name: 'name', label: 'Group Name', required: true }];

export default function StatusGroupBuilder({
  groups,
  loading,
  dashboard,
  onCreate,
  onDelete,
  onRefresh,
  onAddMonitorNode,
}) {
  const [showForm, setShowForm] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(null);
  const [monitors, setMonitors] = useState([]);
  const [monitorsLoaded, setMonitorsLoaded] = useState(false);

  useEffect(() => {
    let mounted = true;
    integrationsApi
      .allMonitors()
      .then((r) => {
        if (mounted) {
          setMonitors(r.data || []);
          setMonitorsLoaded(true);
        }
      })
      .catch(() => {
        if (mounted) setMonitorsLoaded(true);
      });
    return () => {
      mounted = false;
    };
  }, []);

  const global_ = dashboard?.global_;

  return (
    <div style={{ flex: 1, padding: 16, overflowY: 'auto' }}>
      {/* Dashboard summary pill */}
      {global_ && (
        <div
          style={{
            display: 'flex',
            gap: 16,
            marginBottom: 16,
            padding: '10px 14px',
            background: 'var(--color-surface)',
            borderRadius: 8,
            border: '1px solid var(--color-border)',
            flexWrap: 'wrap',
          }}
        >
          <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>7d uptime</span>
          <strong
            style={{ fontSize: 14, color: global_?.avg_uptime_pct >= 99 ? '#22c55e' : '#f59e0b' }}
          >
            {global_?.avg_uptime_pct != null ? `${global_.avg_uptime_pct.toFixed(1)}%` : '—'}
          </strong>
          <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
            {global_?.groups_total ?? 0} groups · {global_?.incidents_7d ?? 0} incidents
          </span>
          <button
            className="btn"
            style={{ marginLeft: 'auto', fontSize: 11, padding: '2px 8px' }}
            onClick={onRefresh}
          >
            ↻ Refresh
          </button>
        </div>
      )}

      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 8,
        }}
      >
        <span style={{ fontWeight: 600, fontSize: 13 }}>Groups</span>
        <button
          className="btn btn-primary"
          style={{ fontSize: 12, padding: '4px 12px' }}
          onClick={() => setShowForm(true)}
        >
          + Add Group
        </button>
      </div>

      {loading ? (
        <SkeletonTable cols={3} />
      ) : groups.length === 0 ? (
        <p style={{ color: 'var(--color-text-muted)', fontSize: 13 }}>
          No groups yet. Add one to start monitoring.
        </p>
      ) : (
        groups.map((g) => (
          <div key={g.id}>
            <GroupRow group={g} onDelete={(id) => setConfirmDelete({ id, name: g.name })} />
            {/* Render integration_monitor nodes within each group */}
            {(g.nodes || [])
              .filter((n) => n.type === 'integration_monitor')
              .map((n) => (
                <MonitorNodeRow key={n.id} nodeId={n.id} monitors={monitors} />
              ))}
          </div>
        ))
      )}

      {/* Monitor picker — add integration monitors to the first/selected group */}
      {monitorsLoaded && monitors.length > 0 && (
        <MonitorPickerSection
          monitors={monitors}
          groupNodes={groups.flatMap((g) => g.nodes || [])}
          onAddMonitorNode={onAddMonitorNode}
        />
      )}

      <FormModal
        open={showForm}
        title="New Status Group"
        fields={ADD_FIELDS}
        initialValues={{}}
        onSubmit={async (values) => {
          await onCreate(values);
          setShowForm(false);
        }}
        onClose={() => setShowForm(false)}
      />
      <ConfirmDialog
        open={!!confirmDelete}
        message={`Remove group "${confirmDelete?.name}"?`}
        onConfirm={() => {
          onDelete(confirmDelete.id);
          setConfirmDelete(null);
        }}
        onCancel={() => setConfirmDelete(null)}
      />
    </div>
  );
}

StatusGroupBuilder.propTypes = {
  groups: PropTypes.array.isRequired,
  loading: PropTypes.bool.isRequired,
  dashboard: PropTypes.object,
  onCreate: PropTypes.func.isRequired,
  onDelete: PropTypes.func.isRequired,
  onRefresh: PropTypes.func.isRequired,
  onAddMonitorNode: PropTypes.func.isRequired,
};
