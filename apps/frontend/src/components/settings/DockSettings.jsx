import React, { useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import { settingsApi } from '../../api/client';
import { useSettings } from '../../context/SettingsContext';
import { useAuth } from '../../context/AuthContext.jsx';
import { NAV_GROUPS, NAV_MAP, canSeeNavItem, resolveDockPaths } from '../../data/navigation';

export default function DockSettings() {
  const { settings, reloadSettings } = useSettings();
  const { user } = useAuth();
  const [saving, setSaving] = useState(false);
  const [banner, setBanner] = useState(null);
  // Ordered list of paths currently on the dock.
  const [order, setOrder] = useState([]);

  useEffect(() => {
    setOrder(resolveDockPaths(settings).filter((path) => Object.hasOwn(NAV_MAP, path)));
  }, [settings]);

  const groups = useMemo(
    () =>
      NAV_GROUPS.map((group) => ({
        ...group,
        items: group.items.filter((item) => canSeeNavItem(item, group, user)),
      })).filter((group) => group.items.length > 0),
    [user]
  );

  const toggle = (path) => {
    setOrder((prev) => (prev.includes(path) ? prev.filter((p) => p !== path) : [...prev, path]));
  };

  const move = (path, delta) => {
    setOrder((prev) => {
      const from = prev.indexOf(path);
      const to = from + delta;
      if (from < 0 || to < 0 || to >= prev.length) return prev;
      const next = [...prev];
      next.splice(to, 0, next.splice(from, 1)[0]);
      return next;
    });
  };

  const handleSave = async () => {
    setSaving(true);
    setBanner(null);
    try {
      await settingsApi.update({ dock_order: order });
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
        Choose which pages appear in the dock, and the order they appear in. The dock shows them
        left to right in the order listed here.
      </p>

      {groups.map((group) => (
        <div key={group.id} style={S.group}>
          <div style={S.groupLabel}>{group.label}</div>
          <div style={S.list}>
            {group.items.map((item) => {
              const Icon = item.icon;
              const position = order.indexOf(item.path);
              const checked = position >= 0;
              return (
                <div key={item.path} style={S.item}>
                  <input
                    id={`dock-item-${item.path}`}
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggle(item.path)}
                    style={{ marginRight: 10 }}
                  />
                  <Icon size={15} style={{ marginRight: 6, color: 'var(--color-text-muted)' }} />
                  <label htmlFor={`dock-item-${item.path}`} style={{ fontSize: 13 }}>
                    {item.label}
                  </label>
                  {checked && (
                    <span style={S.moveGroup}>
                      <button
                        type="button"
                        style={S.moveBtn}
                        aria-label={`Move ${item.label} up`}
                        disabled={position === 0}
                        onClick={() => move(item.path, -1)}
                      >
                        <ChevronUp size={14} />
                      </button>
                      <button
                        type="button"
                        style={S.moveBtn}
                        aria-label={`Move ${item.label} down`}
                        disabled={position === order.length - 1}
                        onClick={() => move(item.path, 1)}
                      >
                        <ChevronDown size={14} />
                      </button>
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      ))}

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
  group: {
    marginBottom: 14,
  },
  groupLabel: {
    color: 'var(--color-text-muted)',
    fontSize: 11,
    fontWeight: 700,
    textTransform: 'uppercase',
    letterSpacing: '0.06em',
    marginBottom: 6,
  },
  list: {
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
  },
  item: {
    display: 'flex',
    alignItems: 'center',
    width: '100%',
    fontSize: 13,
    padding: '4px 0',
  },
  moveGroup: {
    marginLeft: 'auto',
    display: 'flex',
    gap: 2,
  },
  moveBtn: {
    display: 'flex',
    alignItems: 'center',
    background: 'transparent',
    border: '1px solid var(--color-border)',
    borderRadius: 6,
    color: 'var(--color-text-muted)',
    cursor: 'pointer',
    padding: '2px 4px',
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
