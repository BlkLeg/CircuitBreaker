/**
 * ReservationQueueTab — table of pending IP reservations with approve/reject.
 */
import React, { useState, useMemo } from 'react';
import PropTypes from 'prop-types';
import EntityTable from '../EntityTable';
import ConfirmDialog from '../common/ConfirmDialog';
import SearchBox from '../SearchBox';
import { SkeletonTable } from '../common/SkeletonTable';

const STATUS_COLOR = { pending: '#f59e0b', approved: '#22c55e', rejected: '#ef4444' };

const COLUMNS = [
  { key: 'ip_address', label: 'IP Address' },
  { key: 'hostname', label: 'Hostname', render: (v) => v || '—' },
  { key: 'hardware_id', label: 'Hardware ID', render: (v) => v ?? '—' },
  {
    key: 'status',
    label: 'Status',
    render: (v) => (
      <span style={{ fontWeight: 600, color: STATUS_COLOR[v] ?? 'inherit' }}>{v}</span>
    ),
  },
  {
    key: 'created_at',
    label: 'Requested',
    render: (v) => (v ? new Date(v).toLocaleString() : '—'),
  },
];

export default function ReservationQueueTab({ queue, loading, onApprove, onReject }) {
  const [q, setQ] = useState('');
  const [statusFilter, setStatusFilter] = useState('pending');
  const [confirm, setConfirm] = useState(null);

  const filtered = useMemo(() => {
    let rows = queue;
    if (statusFilter) rows = rows.filter((r) => r.status === statusFilter);
    const lq = q.trim().toLowerCase();
    if (lq)
      rows = rows.filter(
        (r) => r.ip_address?.toLowerCase().includes(lq) || r.hostname?.toLowerCase().includes(lq)
      );
    return rows;
  }, [queue, q, statusFilter]);

  const actions = (row) =>
    row.status === 'pending' ? (
      <div style={{ display: 'flex', gap: 4 }}>
        <button
          className="btn btn-sm"
          style={{
            background: '#22c55e',
            color: '#fff',
            border: 'none',
            padding: '2px 8px',
            borderRadius: 4,
            cursor: 'pointer',
            fontSize: 12,
          }}
          onClick={() => onApprove(row.id)}
        >
          Approve
        </button>
        <button
          className="btn btn-sm"
          style={{
            background: '#ef4444',
            color: '#fff',
            border: 'none',
            padding: '2px 8px',
            borderRadius: 4,
            cursor: 'pointer',
            fontSize: 12,
          }}
          onClick={() => setConfirm(row)}
        >
          Reject
        </button>
      </div>
    ) : null;

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
          <option value="pending">Pending</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
        </select>
      </div>

      {loading ? (
        <SkeletonTable cols={5} />
      ) : filtered.length === 0 ? (
        <p style={{ color: 'var(--color-text-muted)', fontStyle: 'italic' }}>No queue entries.</p>
      ) : (
        <EntityTable columns={COLUMNS} data={filtered} renderActions={actions} />
      )}

      <ConfirmDialog
        open={!!confirm}
        message={`Reject reservation for ${confirm?.ip_address}?`}
        onConfirm={() => {
          onReject(confirm.id);
          setConfirm(null);
        }}
        onCancel={() => setConfirm(null)}
      />
    </div>
  );
}

ReservationQueueTab.propTypes = {
  queue: PropTypes.array.isRequired,
  loading: PropTypes.bool.isRequired,
  onApprove: PropTypes.func.isRequired,
  onReject: PropTypes.func.isRequired,
};
