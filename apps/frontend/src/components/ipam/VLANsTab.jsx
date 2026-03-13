/**
 * VLANsTab — VLAN CRUD table.
 * ≤ 150 LOC, cognitive complexity ≤ 20.
 */
import React, { useState } from 'react';
import PropTypes from 'prop-types';
import EntityTable from '../EntityTable';
import FormModal from '../common/FormModal';
import ConfirmDialog from '../common/ConfirmDialog';
import { SkeletonTable } from '../common/SkeletonTable';

const COLUMNS = [
  { key: 'vlan_id', label: 'VLAN ID' },
  { key: 'name', label: 'Name' },
  { key: 'description', label: 'Description', render: (v) => v || '—' },
];

const FIELDS = [
  { name: 'vlan_id', label: 'VLAN ID (1–4094)', type: 'number', required: true },
  { name: 'name', label: 'Name', required: true },
  { name: 'description', label: 'Description', type: 'textarea' },
];

export default function VLANsTab({ vlans, loading, onCreate, onDelete }) {
  const [showForm, setShowForm] = useState(false);
  const [editTarget, setEditTarget] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(null);

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

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 12 }}>
        <button className="btn btn-primary" onClick={() => setShowForm(true)}>
          + Add VLAN
        </button>
      </div>

      {loading ? (
        <SkeletonTable cols={3} />
      ) : (
        <EntityTable
          columns={COLUMNS}
          data={vlans}
          onEdit={handleEdit}
          onDelete={(row) => setConfirmDelete(row)}
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
    </div>
  );
}

VLANsTab.propTypes = {
  vlans: PropTypes.array.isRequired,
  loading: PropTypes.bool.isRequired,
  onCreate: PropTypes.func.isRequired,
  onDelete: PropTypes.func.isRequired,
};
