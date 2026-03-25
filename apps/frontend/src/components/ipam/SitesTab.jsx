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
  { key: 'location', label: 'Location', render: (v) => v || '—' },
  { key: 'notes', label: 'Notes', render: (v) => v || '—' },
];

const FIELDS = [
  { name: 'name', label: 'Name', required: true },
  { name: 'location', label: 'Location' },
  { name: 'notes', label: 'Notes', type: 'textarea' },
];

export default function SitesTab({ sites, networks, loading, onCreate, onUpdate, onDelete }) {
  const [showForm, setShowForm] = useState(false);
  const [editTarget, setEditTarget] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(null);
  const [expandedSite, setExpandedSite] = useState(null);

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
        <SkeletonTable cols={3} />
      ) : (
        <EntityTable
          columns={COLUMNS}
          data={sites}
          onEdit={handleEdit}
          onDelete={(row) => setConfirmDelete(row)}
          onRowClick={(row) => setExpandedSite(expandedSite?.id === row.id ? null : row)}
        />
      )}

      {expandedSite && (
        <div
          style={{
            marginTop: 8,
            padding: '12px 16px',
            background: 'var(--color-surface)',
            border: '1px solid var(--color-border)',
            borderRadius: 4,
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: 8, fontSize: 13 }}>
            {expandedSite.name} — Networks at this site
          </div>
          {(() => {
            const nets = networks.filter((n) => n.site_id === expandedSite.id);
            if (nets.length === 0)
              return (
                <span style={{ color: 'var(--color-text-muted)', fontSize: 13 }}>
                  No networks assigned to this site.
                </span>
              );
            return (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {nets.map((n) => (
                  <span
                    key={n.id}
                    style={{
                      padding: '2px 10px',
                      borderRadius: 12,
                      background: 'var(--color-surface-raised, var(--color-surface))',
                      border: '1px solid var(--color-border)',
                      fontSize: 12,
                      color: 'var(--color-text)',
                    }}
                  >
                    {n.name}
                    {n.cidr ? ` (${n.cidr})` : ''}
                  </span>
                ))}
              </div>
            );
          })()}
        </div>
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
  networks: PropTypes.array.isRequired,
  loading: PropTypes.bool.isRequired,
  onCreate: PropTypes.func.isRequired,
  onUpdate: PropTypes.func.isRequired,
  onDelete: PropTypes.func.isRequired,
};
