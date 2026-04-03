import React, { useState } from 'react';
import { deviceRolesApi } from '../../api/client';
import { useHardwareRoles } from '../../hooks/useHardwareRoles';
import DeviceRoleModal from './DeviceRoleModal';

const RANK_COLORS = {
  1: '#fabd2f',
  2: '#fabd2f',
  3: '#fabd2f',
  4: 'var(--color-primary)',
  5: 'var(--color-text-muted)',
};

const RANK_LABELS = {
  1: 'WAN Gateway',
  2: 'Core Router',
  3: 'Switching',
  4: 'Near-Chain',
  5: 'Endpoint',
};

const S = {
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
    gap: 12,
  },
  card: {
    display: 'flex',
    flexDirection: 'column',
    background: 'var(--color-surface)',
    border: '1px solid var(--color-border)',
    borderRadius: 8,
    padding: '14px 16px',
    gap: 8,
    transition: 'border-color 0.15s',
  },
  cardHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
  },
  iconBox: {
    width: 36,
    height: 36,
    borderRadius: 8,
    background: 'rgba(255,255,255,0.06)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
    color: 'var(--color-text-muted)',
    fontSize: 15,
  },
  label: {
    fontSize: 13,
    fontWeight: 600,
    color: 'var(--color-text)',
    margin: 0,
    lineHeight: 1.3,
  },
  slug: {
    fontSize: 11,
    color: 'var(--color-primary)',
    background: 'rgba(254,128,25,0.10)',
    padding: '1px 6px',
    borderRadius: 4,
    fontFamily: 'monospace',
    display: 'inline-block',
    marginTop: 2,
  },
  rankBadge: (rank) => ({
    alignSelf: 'flex-start',
    fontSize: 11,
    padding: '2px 8px',
    borderRadius: 10,
    border: `1px solid ${RANK_COLORS[rank] || 'var(--color-text-muted)'}`,
    color: RANK_COLORS[rank] || 'var(--color-text-muted)',
    background: 'transparent',
  }),
  meta: {
    fontSize: 11,
    color: 'var(--color-text-muted)',
    display: 'flex',
    flexDirection: 'column',
    gap: 3,
  },
  metaRow: {
    display: 'flex',
    justifyContent: 'space-between',
  },
  actions: {
    display: 'flex',
    gap: 6,
    marginTop: 4,
    alignItems: 'center',
  },
  btnEdit: {
    padding: '4px 10px',
    borderRadius: 4,
    border: '1px solid var(--color-border)',
    background: 'transparent',
    cursor: 'pointer',
    color: 'var(--color-text-muted)',
    fontSize: 11,
    display: 'flex',
    alignItems: 'center',
    gap: 4,
  },
  btnDelete: {
    padding: '4px 10px',
    borderRadius: 4,
    border: '1px solid rgba(255,84,89,0.4)',
    background: 'transparent',
    cursor: 'pointer',
    color: '#ff5459',
    fontSize: 11,
    display: 'flex',
    alignItems: 'center',
    gap: 4,
  },
  addCard: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    background: 'transparent',
    border: '1px dashed var(--color-border)',
    borderRadius: 8,
    padding: '14px 16px',
    cursor: 'pointer',
    color: 'var(--color-text-muted)',
    fontSize: 13,
    transition: 'border-color 0.15s, color 0.15s',
  },
  loading: {
    fontSize: 13,
    color: 'var(--color-text-muted)',
    padding: '16px 0',
  },
};

export default function DeviceRolesSection() {
  const { roles, icons, isLoading, refetch } = useHardwareRoles();
  const [modalState, setModalState] = useState({ isOpen: false, role: null });

  if (isLoading) return <div style={S.loading}>Loading roles…</div>;

  const handleEdit = (role) => setModalState({ isOpen: true, role });
  const handleCreate = () => setModalState({ isOpen: true, role: null });
  const handleClose = () => setModalState({ isOpen: false, role: null });

  const handleDelete = async (role) => {
    if (!window.confirm(`Delete role "${role.label}"? This cannot be undone.`)) return;
    try {
      await deviceRolesApi.delete(role.id);
      refetch();
    } catch (err) {
      alert(err?.response?.data?.detail || err.message || 'Failed to delete role');
    }
  };

  return (
    <div>
      <div style={S.grid}>
        {roles.map((role) => (
          <div key={role.id} style={S.card}>
            {/* Header: icon + name */}
            <div style={S.cardHeader}>
              <div style={S.iconBox}>
                <i className={`fa-solid ${icons[role.slug] || 'fa-microchip'}`} />
              </div>
              <div>
                <div style={S.label}>{role.label}</div>
                <span style={S.slug}>{role.slug}</span>
              </div>
            </div>

            {/* Rank badge */}
            <span style={S.rankBadge(role.rank)}>
              {RANK_LABELS[role.rank] || `Rank ${role.rank}`}
            </span>

            {/* Meta counts */}
            <div style={S.meta}>
              <div style={S.metaRow}>
                <span>Type hints</span>
                <span>{role.device_type_hints?.length || 0}</span>
              </div>
              <div style={S.metaRow}>
                <span>Host patterns</span>
                <span>{role.hostname_patterns?.length || 0}</span>
              </div>
            </div>

            {/* Actions */}
            <div style={S.actions}>
              <button style={S.btnEdit} onClick={() => handleEdit(role)}>
                <i className="fa-solid fa-pen-to-square" style={{ fontSize: 10 }} /> Edit
              </button>
              {!role.is_builtin ? (
                <button style={S.btnDelete} onClick={() => handleDelete(role)}>
                  <i className="fa-solid fa-trash" style={{ fontSize: 10 }} /> Delete
                </button>
              ) : (
                <i
                  className="fa-solid fa-lock"
                  style={{ fontSize: 10, color: 'var(--color-text-muted)', marginLeft: 'auto' }}
                  title="Built-in role — slug is protected"
                />
              )}
            </div>
          </div>
        ))}

        {/* Add card */}
        <button style={S.addCard} onClick={handleCreate}>
          <i className="fa-solid fa-plus" style={{ fontSize: 18 }} />
          New Role
        </button>
      </div>

      <DeviceRoleModal
        isOpen={modalState.isOpen}
        role={modalState.role}
        onClose={handleClose}
        onSuccess={refetch}
      />
    </div>
  );
}
