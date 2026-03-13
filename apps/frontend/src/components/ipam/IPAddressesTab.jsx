/**
 * IPAddressesTab — filterable table of IP addresses with add / delete / network-scan.
 * ≤ 150 LOC, cognitive complexity ≤ 20.
 */
import React, { useState, useMemo } from 'react';
import PropTypes from 'prop-types';
import EntityTable from '../EntityTable';
import FormModal from '../common/FormModal';
import ConfirmDialog from '../common/ConfirmDialog';
import SearchBox from '../SearchBox';
import { SkeletonTable } from '../common/SkeletonTable';

const STATUS_BADGE = {
  free: '#3b82f6',
  allocated: '#22c55e',
  reserved: '#f59e0b',
  dhcp: '#a78bfa',
};

const COLUMNS = (networks) => [
  { key: 'address', label: 'Address' },
  {
    key: 'status',
    label: 'Status',
    render: (v) => (
      <span style={{ fontWeight: 600, color: STATUS_BADGE[v] ?? 'inherit' }}>{v ?? '—'}</span>
    ),
  },
  { key: 'hostname', label: 'Hostname', render: (v) => v || '—' },
  {
    key: 'network_id',
    label: 'Network',
    render: (v) => networks.find((n) => n.id === v)?.name ?? '—',
  },
];

const FIELDS = (networks) => [
  { name: 'address', label: 'IP Address', required: true },
  { name: 'hostname', label: 'Hostname' },
  {
    name: 'status',
    label: 'Status',
    type: 'select',
    options: ['free', 'allocated', 'reserved', 'dhcp'].map((v) => ({ value: v, label: v })),
  },
  {
    name: 'network_id',
    label: 'Network',
    type: 'select',
    options: networks.map((n) => ({ value: n.id, label: n.name })),
  },
];

export default function IPAddressesTab({ ips, networks, loading, onAdd, onDelete, onScanNetwork }) {
  const [q, setQ] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [scanNetworkId, setScanNetworkId] = useState('');
  const [confirmDelete, setConfirmDelete] = useState(null);

  const filtered = useMemo(() => {
    const lq = q.trim().toLowerCase();
    return lq ? ips.filter((ip) => ip.address?.includes(lq) || ip.hostname?.includes(lq)) : ips;
  }, [ips, q]);

  const handleDelete = (row) => setConfirmDelete(row);
  const handleScan = () => {
    if (!scanNetworkId) return;
    onScanNetwork(Number(scanNetworkId));
    setScanNetworkId('');
  };

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
        <SearchBox value={q} onChange={setQ} />
        <select
          className="filter-select"
          value={scanNetworkId}
          onChange={(e) => setScanNetworkId(e.target.value)}
          title="Select network to scan"
        >
          <option value="">Scan network…</option>
          {networks
            .filter((n) => n.cidr)
            .map((n) => (
              <option key={n.id} value={n.id}>
                {n.name} ({n.cidr})
              </option>
            ))}
        </select>
        <button className="btn" onClick={handleScan} disabled={!scanNetworkId}>
          Scan
        </button>
        <button
          className="btn btn-primary"
          style={{ marginLeft: 'auto' }}
          onClick={() => setShowForm(true)}
        >
          + Add IP
        </button>
      </div>

      {loading ? (
        <SkeletonTable cols={4} />
      ) : (
        <EntityTable columns={COLUMNS(networks)} data={filtered} onDelete={handleDelete} />
      )}

      <FormModal
        open={showForm}
        title="Add IP Address"
        fields={FIELDS(networks)}
        initialValues={{ status: 'free' }}
        onSubmit={async (values) => {
          await onAdd(values);
          setShowForm(false);
        }}
        onClose={() => setShowForm(false)}
      />
      <ConfirmDialog
        open={!!confirmDelete}
        message={`Remove ${confirmDelete?.address}?`}
        onConfirm={() => {
          onDelete(confirmDelete.id);
          setConfirmDelete(null);
        }}
        onCancel={() => setConfirmDelete(null)}
      />
    </div>
  );
}

IPAddressesTab.propTypes = {
  ips: PropTypes.array.isRequired,
  networks: PropTypes.array.isRequired,
  loading: PropTypes.bool.isRequired,
  onAdd: PropTypes.func.isRequired,
  onDelete: PropTypes.func.isRequired,
  onScanNetwork: PropTypes.func.isRequired,
};
