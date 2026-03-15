/**
 * VLANsTab — VLAN CRUD table with network association column + detail drawer.
 */
import React, { useState } from 'react';
import PropTypes from 'prop-types';
import EntityTable from '../EntityTable';
import FormModal from '../common/FormModal';
import ConfirmDialog from '../common/ConfirmDialog';
import { SkeletonTable } from '../common/SkeletonTable';
import VLANDetailDrawer from './VLANDetailDrawer';
import VLANMatrixView from './VLANMatrixView';
/* ipamApi imported when direct VLAN CRUD is wired up */

const COLUMNS = (networkMap) => [
  { key: 'vlan_id', label: 'VLAN ID' },
  { key: 'name', label: 'Name' },
  { key: 'description', label: 'Description', render: (v) => v || '—' },
  {
    key: 'network_ids',
    label: 'Networks',
    render: (v) => {
      if (!v || v.length === 0) return '—';
      return (
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          {v.map((nid) => (
            <span
              key={nid}
              style={{
                fontSize: 11,
                padding: '1px 6px',
                borderRadius: 3,
                background: 'var(--color-primary-alpha, rgba(254,128,25,0.1))',
                color: 'var(--color-primary)',
                fontWeight: 500,
              }}
            >
              {networkMap[nid] || `#${nid}`}
            </span>
          ))}
        </div>
      );
    },
  },
];

const FIELDS = [
  { name: 'vlan_id', label: 'VLAN ID (1–4094)', type: 'number', required: true },
  { name: 'name', label: 'Name', required: true },
  { name: 'description', label: 'Description', type: 'textarea' },
];

export default function VLANsTab({ vlans, networks, loading, onCreate, onDelete }) {
  const [showForm, setShowForm] = useState(false);
  const [editTarget, setEditTarget] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(null);
  const [detailVlan, setDetailVlan] = useState(null);
  const [showMatrix, setShowMatrix] = useState(false);

  const networkMap = {};
  (networks || []).forEach((n) => {
    networkMap[n.id] = n.name;
  });

  const handleEdit = (row) => {
    setEditTarget(row);
    setShowForm(true);
  };
  const handleClose = () => {
    setShowForm(false);
    setEditTarget(null);
  };

  const handleSubmit = async (values) => {
    await onCreate({ ...values, vlan_id: Number(values.vlan_id) });
    handleClose();
  };

  const handleRowClick = (row) => setDetailVlan(row);

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginBottom: 12 }}>
        <button className="btn" onClick={() => setShowMatrix(!showMatrix)}>
          {showMatrix ? 'Table View' : 'Matrix View'}
        </button>
        <button className="btn btn-primary" onClick={() => setShowForm(true)}>
          + Add VLAN
        </button>
      </div>

      {showMatrix ? (
        <VLANMatrixView />
      ) : loading ? (
        <SkeletonTable cols={4} />
      ) : (
        <EntityTable
          columns={COLUMNS(networkMap)}
          data={vlans}
          onEdit={handleEdit}
          onDelete={(row) => setConfirmDelete(row)}
          onRowClick={handleRowClick}
        />
      )}

      <FormModal
        open={showForm}
        title={editTarget ? 'Edit VLAN' : 'New VLAN'}
        fields={FIELDS}
        initialValues={editTarget ?? {}}
        onSubmit={handleSubmit}
        onClose={handleClose}
      />
      <ConfirmDialog
        open={!!confirmDelete}
        message={`Delete VLAN "${confirmDelete?.name}"?`}
        onConfirm={() => {
          onDelete(confirmDelete.id);
          setConfirmDelete(null);
        }}
        onCancel={() => setConfirmDelete(null)}
      />

      {detailVlan && (
        <VLANDetailDrawer
          vlan={detailVlan}
          allNetworks={networks || []}
          onClose={() => setDetailVlan(null)}
        />
      )}
    </div>
  );
}

VLANsTab.propTypes = {
  vlans: PropTypes.array.isRequired,
  networks: PropTypes.array,
  loading: PropTypes.bool.isRequired,
  onCreate: PropTypes.func.isRequired,
  onDelete: PropTypes.func.isRequired,
};
