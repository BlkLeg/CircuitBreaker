/**
 * RackPage — rack list + U-slot diagram viewer.
 * Thin shell: data owned by useRacksData, diagram by RackDiagram.
 * ≤ 150 LOC, cognitive complexity ≤ 20.
 */
import React, { useState } from 'react';
import { useToast } from '../components/common/Toast';
import { useRacksData } from '../hooks/useRacksData';
import RackDiagram from '../components/racks/RackDiagram';
import FormModal from '../components/common/FormModal';
import ConfirmDialog from '../components/common/ConfirmDialog';
import { SkeletonTable } from '../components/common/SkeletonTable';
import FutureFeatureBanner from '../components/common/FutureFeatureBanner';

const FIELDS = [
  { name: 'name', label: 'Name', required: true },
  { name: 'u_height', label: 'U Height', type: 'number' },
  { name: 'location', label: 'Location' },
  { name: 'description', label: 'Description', type: 'textarea' },
];

const SIDEBAR_STYLE = {
  width: 220,
  borderRight: '1px solid var(--color-border)',
  overflowY: 'auto',
  flexShrink: 0,
};

const RACK_ITEM_STYLE = (active) => ({
  padding: '8px 12px',
  cursor: 'pointer',
  background: active ? 'color-mix(in srgb, var(--color-primary) 12%, transparent)' : 'transparent',
  borderLeft: active ? '3px solid var(--color-primary)' : '3px solid transparent',
  fontWeight: active ? 600 : 400,
  fontSize: 13,
});

export default function RackPage() {
  const toast = useToast();
  const { racks, hardware, loading, createRack, updateRack, deleteRack } = useRacksData(toast);
  const [selectedId, setSelectedId] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [editTarget, setEditTarget] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(null);

  const selected = racks.find((r) => r.id === selectedId) ?? racks[0] ?? null;

  const handleSubmit = async (values) => {
    const data = { ...values, u_height: values.u_height ? Number(values.u_height) : undefined };
    if (editTarget) {
      await updateRack(editTarget.id, data);
    } else {
      await createRack(data);
    }
    setShowForm(false);
    setEditTarget(null);
  };

  const handleEdit = (rack) => {
    setEditTarget(rack);
    setShowForm(true);
  };
  const handleClose = () => {
    setShowForm(false);
    setEditTarget(null);
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>Racks</h2>
        <button className="btn btn-primary" onClick={() => setShowForm(true)}>
          + Add Rack
        </button>
      </div>
      <FutureFeatureBanner message="Racks is currently in early rollout. Additional rack operations and visual tooling are planned as future features." />

      {loading ? (
        <SkeletonTable cols={2} />
      ) : (
        <div style={{ display: 'flex', gap: 0, flex: 1, height: 'calc(100vh - 160px)' }}>
          {/* Rack list sidebar */}
          <div style={SIDEBAR_STYLE}>
            {racks.length === 0 && (
              <p style={{ padding: 12, fontSize: 13, color: 'var(--color-text-muted)' }}>
                No racks yet.
              </p>
            )}
            {racks.map((rack) => (
              <div
                key={rack.id}
                style={RACK_ITEM_STYLE(selected?.id === rack.id)}
                onClick={() => setSelectedId(rack.id)}
              >
                <div>{rack.name}</div>
                {rack.location && (
                  <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
                    {rack.location}
                  </div>
                )}
                <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
                  <button
                    className="btn"
                    style={{ fontSize: 11, padding: '2px 8px' }}
                    onClick={(e) => {
                      e.stopPropagation();
                      handleEdit(rack);
                    }}
                  >
                    Edit
                  </button>
                  <button
                    className="btn btn-danger"
                    style={{ fontSize: 11, padding: '2px 8px' }}
                    onClick={(e) => {
                      e.stopPropagation();
                      setConfirmDelete(rack);
                    }}
                  >
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>

          {/* Diagram panel */}
          <div style={{ flex: 1, padding: 16, overflowY: 'auto' }}>
            {selected ? (
              <RackDiagram rack={selected} hardware={hardware} />
            ) : (
              <p style={{ color: 'var(--color-text-muted)', fontSize: 13 }}>
                Select a rack to view its diagram.
              </p>
            )}
          </div>
        </div>
      )}

      <FormModal
        open={showForm}
        title={editTarget ? 'Edit Rack' : 'New Rack'}
        fields={FIELDS}
        initialValues={editTarget ?? {}}
        onSubmit={handleSubmit}
        onClose={handleClose}
      />
      <ConfirmDialog
        open={!!confirmDelete}
        message={`Delete rack "${confirmDelete?.name}"?`}
        onConfirm={() => {
          deleteRack(confirmDelete.id);
          setConfirmDelete(null);
        }}
        onCancel={() => setConfirmDelete(null)}
      />
    </div>
  );
}
