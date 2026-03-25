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

export default function VLANsTab({ vlans, networks, loading, onCreate, onUpdate, onDelete }) {
  const [showForm, setShowForm] = useState(false);
  const [editTarget, setEditTarget] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(null);
  const [expandedVlan, setExpandedVlan] = useState(null);

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
      await onUpdate(editTarget.id, { ...values, vlan_id: Number(values.vlan_id) });
    } else {
      await onCreate({ ...values, vlan_id: Number(values.vlan_id) });
    }
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
          onRowClick={(row) => setExpandedVlan(expandedVlan?.id === row.id ? null : row)}
        />
      )}

      {expandedVlan && (
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
            VLAN {expandedVlan.vlan_id} — Referenced Networks
          </div>
          {(() => {
            const refs = networks.filter((n) => n.vlan_id === expandedVlan.vlan_id);
            if (refs.length === 0)
              return (
                <span style={{ color: 'var(--color-text-muted)', fontSize: 13 }}>
                  No networks use this VLAN.
                </span>
              );
            return (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {refs.map((n) => (
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
  networks: PropTypes.array.isRequired,
  loading: PropTypes.bool.isRequired,
  onCreate: PropTypes.func.isRequired,
  onUpdate: PropTypes.func.isRequired,
  onDelete: PropTypes.func.isRequired,
};
