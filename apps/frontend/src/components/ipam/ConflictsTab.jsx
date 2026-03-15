/**
 * ConflictsTab — table of IP conflicts with resolve/dismiss actions.
 */
import React, { useState, useMemo } from 'react';
import PropTypes from 'prop-types';
import EntityTable from '../EntityTable';
import SearchBox from '../SearchBox';
import { SkeletonTable } from '../common/SkeletonTable';
import ConflictResolveModal from './ConflictResolveModal';

const STATUS_COLOR = { open: '#ef4444', resolved: '#22c55e', dismissed: '#6b7280' };

const COLUMNS = [
  { key: 'address', label: 'IP Address' },
  { key: 'conflict_type', label: 'Type' },
  {
    key: 'entity_a_type',
    label: 'Entity A',
    render: (v, row) => `${v} #${row.entity_a_id}`,
  },
  {
    key: 'entity_b_type',
    label: 'Entity B',
    render: (v, row) => `${v} #${row.entity_b_id}`,
  },
  {
    key: 'status',
    label: 'Status',
    render: (v) => (
      <span style={{ fontWeight: 600, color: STATUS_COLOR[v] ?? 'inherit' }}>{v}</span>
    ),
  },
  {
    key: 'created_at',
    label: 'Detected',
    render: (v) => (v ? new Date(v).toLocaleString() : '—'),
  },
];

export default function ConflictsTab({ conflicts, loading, onResolve, onDismiss }) {
  const [q, setQ] = useState('');
  const [statusFilter, setStatusFilter] = useState('open');
  const [resolveTarget, setResolveTarget] = useState(null);

  const filtered = useMemo(() => {
    let rows = conflicts;
    if (statusFilter) rows = rows.filter((r) => r.status === statusFilter);
    const lq = q.trim().toLowerCase();
    if (lq) rows = rows.filter((r) => r.address?.toLowerCase().includes(lq));
    return rows;
  }, [conflicts, q, statusFilter]);

  const actions = (row) =>
    row.status === 'open' ? (
      <div style={{ display: 'flex', gap: 4 }}>
        <button
          className="btn btn-sm"
          style={{
            background: 'var(--color-primary)',
            color: '#fff',
            border: 'none',
            padding: '2px 8px',
            borderRadius: 4,
            cursor: 'pointer',
            fontSize: 12,
          }}
          onClick={() => setResolveTarget(row)}
        >
          Resolve
        </button>
        <button
          className="btn btn-sm"
          style={{
            background: '#6b7280',
            color: '#fff',
            border: 'none',
            padding: '2px 8px',
            borderRadius: 4,
            cursor: 'pointer',
            fontSize: 12,
          }}
          onClick={() => onDismiss(row.id)}
        >
          Dismiss
        </button>
      </div>
    ) : (
      <span style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>
        {row.resolution || row.status}
      </span>
    );

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
        <SearchBox value={q} onChange={setQ} />
        <select
          className="filter-select"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          <option value="">All</option>
          <option value="open">Open</option>
          <option value="resolved">Resolved</option>
          <option value="dismissed">Dismissed</option>
        </select>
      </div>

      {loading ? (
        <SkeletonTable cols={6} />
      ) : filtered.length === 0 ? (
        <p style={{ color: 'var(--color-text-muted)', fontStyle: 'italic' }}>No conflicts.</p>
      ) : (
        <EntityTable columns={COLUMNS} data={filtered} renderActions={actions} />
      )}

      {resolveTarget && (
        <ConflictResolveModal
          conflict={resolveTarget}
          onResolve={async (data) => {
            await onResolve(resolveTarget.id, data);
            setResolveTarget(null);
          }}
          onClose={() => setResolveTarget(null)}
        />
      )}
    </div>
  );
}

ConflictsTab.propTypes = {
  conflicts: PropTypes.array.isRequired,
  loading: PropTypes.bool.isRequired,
  onResolve: PropTypes.func.isRequired,
  onDismiss: PropTypes.func.isRequired,
};
