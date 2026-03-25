/**
 * IPAddressesTab — filterable table of IP addresses with add / delete / network-scan.
 * ≤ 150 LOC, cognitive complexity ≤ 20.
 */
import React, { useState, useMemo, useEffect, useCallback } from 'react';
import PropTypes from 'prop-types';
import EntityTable from '../EntityTable';
import FormModal from '../common/FormModal';
import ConfirmDialog from '../common/ConfirmDialog';
import SearchBox from '../SearchBox';
import { SkeletonTable } from '../common/SkeletonTable';
import HardwareDetail from '../details/HardwareDetail';
import { hardwareApi } from '../../api/client';

function StatusBadge({ status }) {
  const style =
    {
      free: { color: 'var(--color-text-muted)' },
      allocated: { color: 'var(--color-status-up, #22c55e)' },
      reserved: { color: 'var(--color-warning, #f59e0b)' },
      dhcp: { color: 'var(--color-accent)' },
      seen: { color: 'var(--color-text-muted)', fontStyle: 'italic' },
    }[status] ?? {};
  return <span style={{ fontWeight: 600, ...style }}>{status ?? '—'}</span>;
}

StatusBadge.propTypes = { status: PropTypes.string };

export default function IPAddressesTab({
  ips,
  networks,
  loading,
  onAdd,
  onUpdate,
  onDelete,
  onScanNetwork,
}) {
  const [q, setQ] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [scanNetworkId, setScanNetworkId] = useState('');
  const [confirmDelete, setConfirmDelete] = useState(null);
  const [sourceFilter, setSourceFilter] = useState('all'); // 'all' | 'manual' | 'discovered'
  const [detailHardware, setDetailHardware] = useState(null); // hardware object for HardwareDetail drawer
  const [editNotesRow, setEditNotesRow] = useState(null); // row for notes editing
  const [notesValue, setNotesValue] = useState('');
  const [hardware, setHardware] = useState([]);

  useEffect(() => {
    hardwareApi
      .list()
      .then((r) => setHardware(r.data ?? []))
      .catch(() => {});
  }, []);

  const COLUMNS = useMemo(
    () => [
      {
        key: 'source',
        label: 'Source',
        render: (_, row) => {
          const isDiscovered = row.source === 'discovered';
          return (
            <span
              style={{
                padding: '2px 6px',
                borderRadius: 3,
                fontSize: 10,
                fontWeight: 700,
                background: isDiscovered
                  ? 'var(--color-info-bg, #1d3a4f)'
                  : 'var(--color-surface-raised, #504945)',
                color: isDiscovered ? 'var(--color-info, #83a598)' : 'var(--color-text)',
                letterSpacing: '0.05em',
              }}
            >
              {isDiscovered ? 'DISCOVERED' : 'MANUAL'}
            </span>
          );
        },
      },
      { key: 'address', label: 'Address' },
      { key: 'hostname', label: 'Hostname', render: (v) => v || '—' },
      {
        key: 'status',
        label: 'Status',
        render: (v) => <StatusBadge status={v} />,
      },
      {
        key: 'hardware_id',
        label: 'Hardware',
        render: (v) => {
          const hw = hardware.find((h) => h.id === v);
          if (!hw) return <span style={{ color: 'var(--color-text-muted)' }}>—</span>;
          return (
            <button
              className="link-btn"
              style={{
                color: 'var(--color-accent)',
                cursor: 'pointer',
                background: 'none',
                border: 'none',
                padding: 0,
                fontSize: 'inherit',
              }}
              onClick={(e) => {
                e.stopPropagation();
                setDetailHardware(hw);
              }}
            >
              {hw.name} →
            </button>
          );
        },
      },
      {
        key: 'network_id',
        label: 'Network',
        render: (v) => networks.find((n) => n.id === v)?.name ?? '—',
      },
      {
        key: 'notes',
        label: 'Notes',
        render: (v, row) => {
          const isDiscovered = row.source === 'discovered';
          if (isDiscovered) return <span style={{ color: 'var(--color-text-muted)' }}>—</span>;
          return (
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <span
                style={{
                  maxWidth: 160,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                  color: v ? 'inherit' : 'var(--color-text-muted)',
                }}
              >
                {v || '—'}
              </span>
              <button
                style={{
                  background: 'none',
                  border: 'none',
                  cursor: 'pointer',
                  color: 'var(--color-text-muted)',
                  padding: '0 2px',
                  fontSize: 12,
                }}
                title="Edit notes"
                onClick={(e) => {
                  e.stopPropagation();
                  setEditNotesRow(row);
                  setNotesValue(v ?? '');
                }}
              >
                ✎
              </button>
            </div>
          );
        },
      },
    ],
    [hardware, networks, onUpdate]
  );

  const FIELDS = useMemo(
    () => [
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
      { name: 'notes', label: 'Notes', type: 'textarea' },
    ],
    [networks]
  );

  const filtered = useMemo(() => {
    let list = ips;
    if (sourceFilter !== 'all') {
      list = list.filter((ip) =>
        sourceFilter === 'discovered' ? ip.source === 'discovered' : ip.source !== 'discovered'
      );
    }
    const lq = q.trim().toLowerCase();
    if (lq) list = list.filter((ip) => ip.address?.includes(lq) || ip.hostname?.includes(lq));
    return list;
  }, [ips, q, sourceFilter]);

  const handleDelete = useCallback(
    (id) => {
      const row = ips.find((ip) => ip.id === id);
      if (!row || row.source === 'discovered') return;
      setConfirmDelete(row);
    },
    [ips]
  );

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

      <div style={{ display: 'flex', gap: 4, marginBottom: 10 }}>
        {['all', 'manual', 'discovered'].map((f) => (
          <button
            key={f}
            onClick={() => setSourceFilter(f)}
            style={{
              padding: '3px 10px',
              borderRadius: 3,
              fontSize: 11,
              fontWeight: sourceFilter === f ? 700 : 400,
              cursor: 'pointer',
              border: '1px solid var(--color-border)',
              background: sourceFilter === f ? 'var(--color-accent)' : 'var(--color-surface)',
              color: sourceFilter === f ? 'var(--color-bg)' : 'var(--color-text-muted)',
              textTransform: 'capitalize',
            }}
          >
            {f}
          </button>
        ))}
      </div>

      {loading ? (
        <SkeletonTable cols={7} />
      ) : (
        <EntityTable columns={COLUMNS} data={filtered} onDelete={(row) => handleDelete(row.id)} />
      )}

      <FormModal
        open={showForm}
        title="Add IP Address"
        fields={FIELDS}
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

      {editNotesRow && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.5)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
          }}
          onClick={() => setEditNotesRow(null)}
        >
          <div
            style={{
              background: 'var(--color-bg-secondary, var(--color-surface))',
              border: '1px solid var(--color-border)',
              borderRadius: 6,
              padding: 20,
              width: 360,
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ marginBottom: 8, fontWeight: 600 }}>Notes — {editNotesRow.address}</div>
            <textarea
              value={notesValue}
              onChange={(e) => setNotesValue(e.target.value)}
              style={{
                width: '100%',
                minHeight: 80,
                padding: 8,
                boxSizing: 'border-box',
                background: 'var(--color-surface)',
                border: '1px solid var(--color-border)',
                borderRadius: 4,
                color: 'inherit',
                resize: 'vertical',
              }}
              autoFocus
            />
            <div style={{ display: 'flex', gap: 8, marginTop: 10, justifyContent: 'flex-end' }}>
              <button className="btn" onClick={() => setEditNotesRow(null)}>
                Cancel
              </button>
              <button
                className="btn btn-primary"
                onClick={async () => {
                  await onUpdate(editNotesRow.id, { notes: notesValue });
                  setEditNotesRow(null);
                }}
              >
                Save
              </button>
            </div>
          </div>
        </div>
      )}

      <HardwareDetail
        hardware={detailHardware}
        isOpen={!!detailHardware}
        onClose={() => setDetailHardware(null)}
      />
    </div>
  );
}

IPAddressesTab.propTypes = {
  ips: PropTypes.array.isRequired,
  networks: PropTypes.array.isRequired,
  loading: PropTypes.bool.isRequired,
  onAdd: PropTypes.func.isRequired,
  onUpdate: PropTypes.func.isRequired,
  onDelete: PropTypes.func.isRequired,
  onScanNetwork: PropTypes.func.isRequired,
};
