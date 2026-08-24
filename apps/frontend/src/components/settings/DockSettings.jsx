import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import { settingsApi } from '../../api/client';
import { useSettings } from '../../context/SettingsContext';
import { useAuth } from '../../context/AuthContext.jsx';
import {
  NAV_GROUPS,
  canSeeNavItem,
  navGroupOf,
  navItem,
  resolveDockPaths,
} from '../../data/navigation';

export default function DockSettings() {
  const { settings, reloadSettings } = useSettings();
  const { user } = useAuth();
  const [saving, setSaving] = useState(false);
  const [banner, setBanner] = useState(null);
  // Ordered list of paths currently on the dock.
  const [order, setOrder] = useState([]);
  // Announced to screen readers after a move; the visible list moves at the same time.
  const [announcement, setAnnouncement] = useState('');

  useEffect(() => {
    setOrder(resolveDockPaths(settings).filter((path) => navItem(path) !== null));
  }, [settings]);

  const groups = useMemo(
    () =>
      NAV_GROUPS.map((group) => ({
        ...group,
        items: group.items.filter((item) => canSeeNavItem(item, group, user)),
      })).filter((group) => group.items.length > 0),
    [user]
  );

  const isShown = useCallback(
    (path) => {
      const item = navItem(path);
      return item !== null && canSeeNavItem(item, navGroupOf(path), user);
    },
    [user]
  );

  /**
   * The dock as the user will actually see it, left to right. The picker below is
   * grouped by taxonomy, so position cannot be read off it — this list is where order
   * lives, and it is the list the up/down controls move things in.
   */
  const dockList = useMemo(() => order.filter(isShown).map(navItem), [order, isShown]);

  const toggle = (path) => {
    setOrder((prev) => (prev.includes(path) ? prev.filter((p) => p !== path) : [...prev, path]));
  };

  /**
   * Swaps with the adjacent *rendered* neighbour. `order` can hold paths this user
   * cannot see, so stepping by raw index would silently trade places with a row that
   * is not on screen.
   */
  const move = (path, delta) => {
    const shown = order.filter(isShown);
    const from = shown.indexOf(path);
    const to = from + delta;
    if (from < 0 || to < 0 || to >= shown.length) return;
    const a = order.indexOf(path);
    const b = order.indexOf(shown.at(to));
    const [moved, displaced] = [order.at(a), order.at(b)];
    setOrder(order.map((p, i) => (i === a ? displaced : i === b ? moved : p)));
    setAnnouncement(`${navItem(path).label} moved to position ${to + 1} of ${shown.length}.`);
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
        Choose which pages appear in the dock below, then arrange them in “On the dock” — that list
        reads left to right exactly as the dock does.
      </p>

      <div style={S.group}>
        <div style={S.groupLabel}>On the dock</div>
        {dockList.length === 0 ? (
          <p style={S.empty}>Nothing is on the dock. Tick a page below to add it.</p>
        ) : (
          <ol style={S.orderedList}>
            {dockList.map((item, position) => {
              const Icon = item.icon;
              return (
                <li key={item.path} style={S.orderedItem}>
                  <span style={S.ordinal}>{position + 1}</span>
                  <Icon size={15} style={{ marginRight: 6, color: 'var(--color-text-muted)' }} />
                  <span style={{ fontSize: 13 }}>{item.label}</span>
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
                      disabled={position === dockList.length - 1}
                      onClick={() => move(item.path, 1)}
                    >
                      <ChevronDown size={14} />
                    </button>
                  </span>
                </li>
              );
            })}
          </ol>
        )}
      </div>

      <div aria-live="polite" style={S.srOnly}>
        {announcement}
      </div>

      {groups.map((group) => (
        <div key={group.id} style={S.group}>
          <div style={S.groupLabel}>{group.label}</div>
          <div style={S.list}>
            {group.items.map((item) => {
              const Icon = item.icon;
              const checked = order.includes(item.path);
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
  empty: {
    fontSize: 12,
    color: 'var(--color-text-muted)',
    margin: '4px 0 0',
  },
  orderedList: {
    listStyle: 'none',
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
    margin: 0,
    padding: 0,
  },
  orderedItem: {
    display: 'flex',
    alignItems: 'center',
    width: '100%',
    fontSize: 13,
    padding: '4px 0',
  },
  ordinal: {
    color: 'var(--color-text-muted)',
    fontSize: 11,
    fontVariantNumeric: 'tabular-nums',
    minWidth: 16,
    marginRight: 8,
  },
  srOnly: {
    position: 'absolute',
    width: 1,
    height: 1,
    overflow: 'hidden',
    clip: 'rect(0 0 0 0)',
    whiteSpace: 'nowrap',
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
