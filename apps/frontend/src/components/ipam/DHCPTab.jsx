/**
 * DHCPTab — DHCP pool management with expandable lease lists.
 */
import React, { useState, useEffect } from 'react';
import PropTypes from 'prop-types';
import EntityTable from '../EntityTable';
import FormModal from '../common/FormModal';
import ConfirmDialog from '../common/ConfirmDialog';
import { SkeletonTable } from '../common/SkeletonTable';
import { ipamApi } from '../../api/client';

/* eslint-disable @typescript-eslint/no-unused-vars -- will be used when pool table is wired up */
const POOL_COLUMNS = (networks) => [
  { key: 'name', label: 'Pool Name' },
  {
    key: 'network_id',
    label: 'Network',
    render: (v) => networks.find((n) => n.id === v)?.name ?? '—',
  },
  { key: 'start_ip', label: 'Start IP' },
  { key: 'end_ip', label: 'End IP' },
  {
    key: 'lease_duration_seconds',
    label: 'Lease Duration',
    render: (v) => {
      const h = Math.floor(v / 3600);
      return h >= 24 ? `${Math.floor(h / 24)}d` : `${h}h`;
    },
  },
  {
    key: 'enabled',
    label: 'Enabled',
    render: (v) => <span style={{ color: v ? '#22c55e' : '#6b7280' }}>{v ? 'Yes' : 'No'}</span>,
  },
];

const POOL_FIELDS = (networks) => [
  { name: 'name', label: 'Pool Name', required: true },
  {
    name: 'network_id',
    label: 'Network',
    type: 'select',
    required: true,
    options: networks
      .filter((n) => n.cidr)
      .map((n) => ({ value: n.id, label: `${n.name} (${n.cidr})` })),
  },
  { name: 'start_ip', label: 'Start IP', required: true },
  { name: 'end_ip', label: 'End IP', required: true },
  { name: 'lease_duration_seconds', label: 'Lease Duration (seconds)', type: 'number' },
];

const LEASE_COLS = [
  { key: 'ip_address', label: 'IP' },
  { key: 'mac_address', label: 'MAC', render: (v) => v || '—' },
  { key: 'hostname', label: 'Hostname', render: (v) => v || '—' },
  {
    key: 'status',
    label: 'Status',
    render: (v) => (
      <span
        style={{
          fontWeight: 600,
          color: v === 'active' ? '#22c55e' : v === 'expired' ? '#ef4444' : '#6b7280',
        }}
      >
        {v}
      </span>
    ),
  },
  {
    key: 'lease_expiry',
    label: 'Expires',
    render: (v) => (v ? new Date(v).toLocaleString() : '—'),
  },
];

function PoolLeases({ poolId }) {
  const [leases, setLeases] = useState([]);
  const [loading, setLoading] = useState(true);
  const [util, setUtil] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        const [lRes, uRes] = await Promise.all([
          ipamApi.listDHCPLeases(poolId),
          ipamApi.dhcpPoolUtilization(poolId),
        ]);
        setLeases(lRes.data ?? []);
        setUtil(uRes.data);
      } catch {
        /* ignore */
      }
      setLoading(false);
    })();
  }, [poolId]);

  if (loading) return <SkeletonTable cols={5} rows={3} />;

  return (
    <div style={{ paddingLeft: 16, paddingBottom: 8 }}>
      {util && (
        <div style={{ marginBottom: 8, fontSize: 12, color: 'var(--color-text-muted)' }}>
          Utilization: <strong>{util.utilization_pct}%</strong> — {util.active_leases} active /{' '}
          {util.total_ips} total
          <div
            style={{
              height: 6,
              background: 'var(--color-border)',
              borderRadius: 3,
              marginTop: 4,
              overflow: 'hidden',
              maxWidth: 300,
            }}
          >
            <div
              style={{
                height: '100%',
                width: `${util.utilization_pct}%`,
                background: util.utilization_pct > 80 ? '#ef4444' : '#22c55e',
                borderRadius: 3,
              }}
            />
          </div>
        </div>
      )}
      {leases.length === 0 ? (
        <p style={{ color: 'var(--color-text-muted)', fontStyle: 'italic', fontSize: 13 }}>
          No leases in this pool.
        </p>
      ) : (
        <EntityTable columns={LEASE_COLS} data={leases} compact />
      )}
    </div>
  );
}

export default function DHCPTab({ pools, networks, loading, onCreate, onDelete }) {
  const [showForm, setShowForm] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(null);
  const [expandedId, setExpandedId] = useState(null);

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, justifyContent: 'flex-end' }}>
        <button className="btn btn-primary" onClick={() => setShowForm(true)}>
          + Add Pool
        </button>
      </div>

      {loading ? (
        <SkeletonTable cols={6} />
      ) : pools.length === 0 ? (
        <p style={{ color: 'var(--color-text-muted)', fontStyle: 'italic' }}>
          No DHCP pools configured.
        </p>
      ) : (
        <div>
          {pools.map((pool) => (
            <div
              key={pool.id}
              style={{
                border: '1px solid var(--color-border)',
                borderRadius: 6,
                marginBottom: 8,
                overflow: 'hidden',
              }}
            >
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  padding: '8px 12px',
                  cursor: 'pointer',
                  background: expandedId === pool.id ? 'var(--color-bg)' : 'transparent',
                  gap: 12,
                }}
                onClick={() => setExpandedId(expandedId === pool.id ? null : pool.id)}
              >
                <span style={{ fontSize: 11, opacity: 0.5 }}>
                  {expandedId === pool.id ? '▼' : '▶'}
                </span>
                <strong style={{ flex: 1 }}>{pool.name}</strong>
                <span style={{ color: 'var(--color-text-muted)', fontSize: 13 }}>
                  {pool.start_ip} – {pool.end_ip}
                </span>
                <span
                  style={{
                    fontSize: 12,
                    color: pool.enabled ? '#22c55e' : '#6b7280',
                    fontWeight: 600,
                  }}
                >
                  {pool.enabled ? 'Active' : 'Disabled'}
                </span>
                <button
                  className="btn btn-sm"
                  style={{
                    background: '#ef4444',
                    color: '#fff',
                    border: 'none',
                    padding: '2px 8px',
                    borderRadius: 4,
                    fontSize: 12,
                  }}
                  onClick={(e) => {
                    e.stopPropagation();
                    setConfirmDelete(pool);
                  }}
                >
                  Delete
                </button>
              </div>
              {expandedId === pool.id && <PoolLeases poolId={pool.id} />}
            </div>
          ))}
        </div>
      )}

      <FormModal
        open={showForm}
        title="Add DHCP Pool"
        fields={POOL_FIELDS(networks)}
        initialValues={{ lease_duration_seconds: 86400 }}
        onSubmit={async (values) => {
          await onCreate(values);
          setShowForm(false);
        }}
        onClose={() => setShowForm(false)}
      />
      <ConfirmDialog
        open={!!confirmDelete}
        message={`Delete pool "${confirmDelete?.name}"?`}
        onConfirm={() => {
          onDelete(confirmDelete.id);
          setConfirmDelete(null);
        }}
        onCancel={() => setConfirmDelete(null)}
      />
    </div>
  );
}

DHCPTab.propTypes = {
  pools: PropTypes.array.isRequired,
  networks: PropTypes.array.isRequired,
  loading: PropTypes.bool.isRequired,
  onCreate: PropTypes.func.isRequired,
  onDelete: PropTypes.func.isRequired,
};
