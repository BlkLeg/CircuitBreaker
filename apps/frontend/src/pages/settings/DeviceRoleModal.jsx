import React, { useState, useEffect } from 'react';
import { deviceRolesApi } from '../../api/client';

const S = {
  overlay: {
    position: 'fixed',
    inset: 0,
    background: 'rgba(0,0,0,0.65)',
    zIndex: 1000,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 16,
  },
  modal: {
    width: '100%',
    maxWidth: 520,
    maxHeight: '90vh',
    display: 'flex',
    flexDirection: 'column',
    background: 'var(--color-surface)',
    border: '1px solid var(--color-border)',
    borderRadius: 10,
    boxShadow: '0 8px 40px rgba(0,0,0,0.4)',
    overflow: 'hidden',
  },
  header: {
    padding: '18px 24px',
    borderBottom: '1px solid var(--color-border)',
    fontSize: 15,
    fontWeight: 600,
    color: 'var(--color-text)',
  },
  body: {
    padding: '20px 24px',
    overflowY: 'auto',
    display: 'flex',
    flexDirection: 'column',
    gap: 16,
  },
  footer: {
    padding: '14px 24px',
    borderTop: '1px solid var(--color-border)',
    display: 'flex',
    justifyContent: 'flex-end',
    gap: 8,
    background: 'rgba(0,0,0,0.15)',
  },
  fieldLabel: {
    display: 'block',
    fontSize: 12,
    fontWeight: 600,
    color: 'var(--color-text-muted)',
    marginBottom: 6,
    textTransform: 'uppercase',
    letterSpacing: '0.04em',
  },
  input: {
    width: '100%',
    padding: '8px 10px',
    background: 'var(--color-bg, #1a1a2e)',
    border: '1px solid var(--color-border)',
    borderRadius: 6,
    color: 'var(--color-text)',
    fontSize: 13,
    boxSizing: 'border-box',
  },
  textarea: {
    width: '100%',
    padding: '8px 10px',
    background: 'var(--color-bg, #1a1a2e)',
    border: '1px solid var(--color-border)',
    borderRadius: 6,
    color: 'var(--color-text)',
    fontSize: 12,
    fontFamily: 'monospace',
    resize: 'vertical',
    boxSizing: 'border-box',
  },
  hint: {
    fontSize: 11,
    color: 'var(--color-text-muted)',
    marginTop: 4,
  },
  row: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: 12,
  },
  builtinNote: {
    fontSize: 12,
    color: 'var(--color-text-muted)',
    background: 'rgba(255,255,255,0.04)',
    border: '1px solid var(--color-border)',
    borderRadius: 6,
    padding: '8px 12px',
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  btnCancel: {
    padding: '7px 16px',
    borderRadius: 6,
    border: '1px solid var(--color-border)',
    background: 'transparent',
    color: 'var(--color-text)',
    fontSize: 13,
    cursor: 'pointer',
  },
  btnSave: (disabled) => ({
    padding: '7px 16px',
    borderRadius: 6,
    border: 'none',
    background: disabled ? 'rgba(254,128,25,0.4)' : 'var(--color-primary)',
    color: '#fff',
    fontSize: 13,
    fontWeight: 600,
    cursor: disabled ? 'not-allowed' : 'pointer',
  }),
};

const RANK_OPTIONS = [
  { value: 1, label: '1 — WAN Gateway' },
  { value: 2, label: '2 — Core Router' },
  { value: 3, label: '3 — Distribution Switch' },
  { value: 4, label: '4 — Near-Chain Access' },
  { value: 5, label: '5 — Endpoint / Leaf' },
];

export default function DeviceRoleModal({ isOpen, role, onClose, onSuccess }) {
  const isEdit = !!role;
  const [isPending, setIsPending] = useState(false);
  const [formData, setFormData] = useState({
    slug: '',
    label: '',
    rank: 5,
    icon_slug: '',
    device_type_hints: '',
    hostname_patterns: '',
  });

  useEffect(() => {
    if (!isOpen) return;
    if (role) {
      setFormData({
        slug: role.slug,
        label: role.label,
        rank: role.rank,
        icon_slug: role.icon_slug || '',
        device_type_hints: (role.device_type_hints || []).join(', '),
        hostname_patterns: (role.hostname_patterns || []).join(', '),
      });
    } else {
      setFormData({
        slug: '',
        label: '',
        rank: 5,
        icon_slug: '',
        device_type_hints: '',
        hostname_patterns: '',
      });
    }
  }, [isOpen, role]);

  const set = (k, v) => setFormData((f) => ({ ...f, [k]: v }));

  const handleSave = async () => {
    setIsPending(true);
    try {
      const payload = {
        label: formData.label,
        rank: Number(formData.rank),
        icon_slug: formData.icon_slug || null,
        device_type_hints: formData.device_type_hints
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean),
        hostname_patterns: formData.hostname_patterns
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean),
      };
      if (isEdit) {
        await deviceRolesApi.update(role.id, payload);
      } else {
        await deviceRolesApi.create({ ...payload, slug: formData.slug });
      }
      if (onSuccess) onSuccess();
      onClose();
    } catch (err) {
      alert(err?.response?.data?.detail || err.message || 'Failed to save role');
    } finally {
      setIsPending(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div style={S.overlay} onClick={onClose}>
      <div style={S.modal} onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div style={S.header}>{isEdit ? `Edit — ${role.label}` : 'New Device Role'}</div>

        {/* Body */}
        <div style={S.body}>
          {isEdit && role.is_builtin && (
            <div style={S.builtinNote}>
              <i className="fa-solid fa-lock" style={{ fontSize: 11 }} />
              Built-in role — slug is protected and cannot be changed.
            </div>
          )}

          {!isEdit && (
            <div>
              <label style={S.fieldLabel}>Slug</label>
              <input
                style={S.input}
                type="text"
                value={formData.slug}
                onChange={(e) => set('slug', e.target.value)}
                placeholder="e.g. smart_tv"
              />
              <p style={S.hint}>Lowercase letters, digits, and underscores only.</p>
            </div>
          )}

          <div>
            <label style={S.fieldLabel}>Label</label>
            <input
              style={S.input}
              type="text"
              value={formData.label}
              onChange={(e) => set('label', e.target.value)}
              placeholder="e.g. Smart TV"
            />
          </div>

          <div style={S.row}>
            <div>
              <label style={S.fieldLabel}>Topology Rank</label>
              <select
                style={S.input}
                value={formData.rank}
                onChange={(e) => set('rank', Number(e.target.value))}
              >
                {RANK_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label style={S.fieldLabel}>FontAwesome Icon</label>
              <input
                style={S.input}
                type="text"
                value={formData.icon_slug}
                onChange={(e) => set('icon_slug', e.target.value)}
                placeholder="e.g. fa-tv"
              />
            </div>
          </div>

          <div>
            <label style={S.fieldLabel}>Device Type Hints</label>
            <textarea
              style={S.textarea}
              rows={2}
              value={formData.device_type_hints}
              onChange={(e) => set('device_type_hints', e.target.value)}
              placeholder="smart_tv, iptv"
            />
            <p style={S.hint}>Comma-separated. Matched against fingerprint device_type values.</p>
          </div>

          <div>
            <label style={S.fieldLabel}>Hostname Patterns</label>
            <textarea
              style={S.textarea}
              rows={2}
              value={formData.hostname_patterns}
              onChange={(e) => set('hostname_patterns', e.target.value)}
              placeholder="bravia, lg-webos, samsung-tv"
            />
            <p style={S.hint}>
              Comma-separated substrings matched case-insensitively against discovered hostnames.
            </p>
          </div>
        </div>

        {/* Footer */}
        <div style={S.footer}>
          <button style={S.btnCancel} onClick={onClose}>
            Cancel
          </button>
          <button style={S.btnSave(isPending)} onClick={handleSave} disabled={isPending}>
            {isPending ? 'Saving…' : 'Save Role'}
          </button>
        </div>
      </div>
    </div>
  );
}
