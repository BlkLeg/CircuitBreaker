import React, { useEffect, useState } from 'react';
import { settingsApi } from '../../api/client';
import { useSettings } from '../../context/SettingsContext';
import { NAV_MAP, DEFAULT_ORDER } from '../Dock';

export default function DockSettings() {
  const { settings, reloadSettings } = useSettings();
  const [saving, setSaving] = useState(false);
  const [banner, setBanner] = useState(null);
  // Local set of hidden paths (paths that are hidden from the dock)
  const [hidden, setHidden] = useState(new Set());

  useEffect(() => {
    setHidden(new Set(settings?.dock_hidden_items ?? []));
  }, [settings?.dock_hidden_items]);

  const toggle = (path) => {
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  const handleSave = async () => {
    setSaving(true);
    setBanner(null);
    try {
      await settingsApi.update({ dock_hidden_items: [...hidden] });
      await reloadSettings();
      setBanner({ type: 'success', msg: 'Dock settings saved.' });
    } catch (err) {
      setBanner({ type: 'error', msg: `Save failed: ${err.message}` });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <p style={S.hint}>
        Choose which pages appear in the dock. Drag items in the dock itself to reorder them.
      </p>

      <div style={S.list}>
        {DEFAULT_ORDER.map((path) => {
          const { icon: Icon, label } = NAV_MAP[path];
          const isHidden = hidden.has(path);
          return (
            <label key={path} style={S.item}>
              <input
                type="checkbox"
                checked={!isHidden}
                onChange={() => toggle(path)}
                style={{ marginRight: 10 }}
              />
              <Icon size={15} style={{ marginRight: 6, color: 'var(--color-text-muted)' }} />
              <span style={{ fontSize: 13 }}>{label}</span>
            </label>
          );
        })}
      </div>

      {banner && <div style={S.banner(banner.type)}>{banner.msg}</div>}

      <button
        className="btn btn-primary btn-sm"
        style={{ marginTop: 16 }}
        onClick={handleSave}
        disabled={saving}
      >
        {saving ? 'Saving…' : 'Save'}
      </button>
    </div>
  );
}

const S = {
  hint: {
    fontSize: 12,
    color: 'var(--color-text-muted)',
    marginBottom: 14,
    marginTop: 0,
  },
  list: {
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
  },
  item: {
    display: 'flex',
    alignItems: 'center',
    cursor: 'pointer',
    fontSize: 13,
    padding: '4px 0',
  },
  banner: (type) => ({
    marginTop: 10,
    padding: '6px 12px',
    borderRadius: 5,
    fontSize: 13,
    background: type === 'success' ? 'rgba(34,197,94,0.12)' : 'rgba(239,68,68,0.12)',
    border: `1px solid ${type === 'success' ? 'rgba(34,197,94,0.3)' : 'rgba(239,68,68,0.3)'}`,
    color: type === 'success' ? '#86efac' : '#fca5a5',
  }),
};
