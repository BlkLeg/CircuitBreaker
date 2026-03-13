/**
 * SitesTab — Site CRUD table.
 * ≤ 150 LOC, cognitive complexity ≤ 20.
 */
import React, { useState } from 'react';
import PropTypes from 'prop-types';
import EntityTable from '../EntityTable';
import FormModal from '../common/FormModal';
import ConfirmDialog from '../common/ConfirmDialog';
import { SkeletonTable } from '../common/SkeletonTable';

const COLUMNS = [
  { key: 'name', label: 'Name' },
  { key: 'description', label: 'Description', render: (v) => v || '—' },
];

const FIELDS = [
  { name: 'name', label: 'Name', required: true },
  { name: 'description', label: 'Description', type: 'textarea' },
];

export default function SitesTab({ sites, loading, onCreate, onUpdate, onDelete }) {
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
    if (editTarget) {
      await onUpdate(editTarget.id, values);
    } else {
      await onCreate(values);
    }
    handleClose();
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 12 }}>
        <button className="btn btn-primary" onClick={() => setShowForm(true)}>
          + Add Site
        </button>
      </div>

      {loading ? (
        <SkeletonTable cols={2} />
      ) : (
        <EntityTable
          columns={COLUMNS}
          data={sites}
          onEdit={handleEdit}
          onDelete={(row) => setConfirmDelete(row)}
        />
      )}

      <FormModal
        open={showForm}
        title={editTarget ? 'Edit Site' : 'New Site'}
        fields={FIELDS}
        initialValues={editTarget ?? {}}
        onSubmit={handleSubmit}
        onClose={handleClose}
      />
      <ConfirmDialog
        open={!!confirmDelete}
        message={`Delete site "${confirmDelete?.name}"?`}
        onConfirm={() => {
          onDelete(confirmDelete.id);
          setConfirmDelete(null);
        }}
        onCancel={() => setConfirmDelete(null)}
      />
    </div>
  );
}

SitesTab.propTypes = {
  sites: PropTypes.array.isRequired,
  loading: PropTypes.bool.isRequired,
  onCreate: PropTypes.func.isRequired,
  onUpdate: PropTypes.func.isRequired,
  onDelete: PropTypes.func.isRequired,
};
