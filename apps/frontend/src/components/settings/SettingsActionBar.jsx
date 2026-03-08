import React from 'react';

const S = {
  container: (visible) => ({
    position: 'fixed',
    bottom: 0,
    left: 0,
    right: 0,
    background: 'var(--color-surface)',
    borderTop: '1px solid var(--color-border)',
    padding: '16px 24px',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    transform: visible ? 'translateY(0)' : 'translateY(100%)',
    transition: 'transform 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
    zIndex: 1000,
    boxShadow: '0 -4px 20px rgba(0, 0, 0, 0.3)',
  }),
  message: {
    fontSize: 14,
    color: 'var(--color-text)',
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  actions: {
    display: 'flex',
    gap: 12,
  },
  badge: {
    background: 'var(--color-primary)',
    color: '#000',
    padding: '2px 8px',
    borderRadius: 10,
    fontSize: 11,
    fontWeight: 700,
  },
};

export default function SettingsActionBar({ isDirty, saving, onSave, onReset }) {
  return (
    <div style={S.container(isDirty || saving)}>
      <div style={S.message}>
        <span style={S.badge}>UNSAVED CHANGES</span>
        <span>You have modified settings. Apply them to the server?</span>
      </div>
      <div style={S.actions}>
        <button className="btn btn-secondary btn-sm" onClick={onReset} disabled={saving}>
          Discard
        </button>
        <button className="btn btn-primary btn-sm" onClick={onSave} disabled={saving}>
          {saving ? 'Saving...' : 'Save Changes'}
        </button>
      </div>
    </div>
  );
}
