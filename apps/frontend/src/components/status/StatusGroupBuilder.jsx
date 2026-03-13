/**
 * StatusGroupBuilder — right-panel group management for the selected status page.
 * Lists groups, allows adding / deleting, and shows a v2 dashboard summary.
 * ≤ 150 LOC, cognitive complexity ≤ 20.
 */
import React, { useState } from 'react';
import PropTypes from 'prop-types';
import FormModal from '../common/FormModal';
import ConfirmDialog from '../common/ConfirmDialog';
import { SkeletonTable } from '../common/SkeletonTable';

const STATUS_COLOR = new Map([
  ['up', '#22c55e'],
  ['degraded', '#f59e0b'],
  ['down', '#ef4444'],
  ['unknown', 'var(--color-text-muted)'],
]);

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

const ADD_FIELDS = [{ name: 'name', label: 'Group Name', required: true }];

export default function StatusGroupBuilder({
  groups,
  loading,
  dashboard,
  onCreate,
  onDelete,
  onRefresh,
}) {
  const [showForm, setShowForm] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(null);

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
          <GroupRow
            key={g.id}
            group={g}
            onDelete={(id) => setConfirmDelete({ id, name: g.name })}
          />
        ))
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
};
