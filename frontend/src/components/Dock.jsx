import React, { useCallback, useEffect, useRef, useState } from 'react';
import { NavLink } from 'react-router-dom';
import { BookOpen, Cpu, GripHorizontal, Layers, Network, ScrollText, Server, Settings, Map } from 'lucide-react';
import { settingsApi } from '../api/client';
import { useSettings } from '../context/SettingsContext';

export const NAV_MAP = {
  '/hardware':      { icon: Cpu,        label: 'Hardware' },
  '/compute-units': { icon: Server,     label: 'Compute'  },
  '/services':      { icon: Layers,     label: 'Services' },
  '/networks':      { icon: Network,    label: 'Network'  },
  '/map':           { icon: Map,        label: 'Map'      },
  '/docs':          { icon: BookOpen,   label: 'Docs'     },
  '/logs':          { icon: ScrollText, label: 'Logs'     },
  '/settings':      { icon: Settings,   label: 'Settings' },
};

export const DEFAULT_ORDER = [
  '/map',
  '/hardware',
  '/compute-units',
  '/services',
  '/networks',
  '/docs',
  '/logs',
  '/settings',
];

function Dock() {
  const navRef = useRef(null);
  const dragItem = useRef(null);
  const dragOver = useRef(null);

  const { settings, reloadSettings } = useSettings();
  const [editMode, setEditMode] = useState(false);
  // localOrder is set optimistically during a drag; cleared after save
  const [localOrder, setLocalOrder] = useState(null);

  // Resolve current display order
  // Merge saved order with DEFAULT_ORDER so new routes added to NAV_MAP
  // always appear even when an older dock_order was previously saved.
  const savedOrder = localOrder ?? (Array.isArray(settings?.dock_order) && settings.dock_order.length > 0 ? settings.dock_order : null);
  const order = savedOrder
    ? [
        ...savedOrder.filter((p) => NAV_MAP[p]),
        ...DEFAULT_ORDER.filter((p) => NAV_MAP[p] && !savedOrder.includes(p)),
      ]
    : DEFAULT_ORDER;

  const hiddenItems = new Set(settings?.dock_hidden_items ?? []);
  const navItems = order
    .filter((path) => NAV_MAP[path] && !hiddenItems.has(path))
    .map((path) => ({ path, ...NAV_MAP[path] }));

  /* ── Horizontal scroll ───────────────────────────────── */
  useEffect(() => {
    const el = navRef.current;
    if (!el) return;
    const onWheel = (e) => {
      if (e.deltaY === 0) return;
      e.preventDefault();
      el.scrollLeft += e.deltaY;
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, []);

  /* ── Exit edit mode on Escape ────────────────────────── */
  useEffect(() => {
    if (!editMode) return;
    const handler = (e) => { if (e.key === 'Escape') setEditMode(false); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [editMode]);

  /* ── Exit edit mode when clicking outside the dock ───── */
  useEffect(() => {
    if (!editMode) return;
    const handler = (e) => {
      if (navRef.current && !navRef.current.contains(e.target)) {
        setEditMode(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [editMode]);

  /* ── Drag handlers ───────────────────────────────────── */
  const handleDragStart = (idx) => { dragItem.current = idx; };
  const handleDragEnter = (idx) => { dragOver.current = idx; };

  const handleDragEnd = useCallback(async () => {
    const from = dragItem.current;
    const to   = dragOver.current;
    dragItem.current = null;
    dragOver.current = null;

    if (from === null || to === null || from === to) return;

    const next = [...order];
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);

    setLocalOrder(next);
    try {
      await settingsApi.update({ dock_order: next });
      await reloadSettings();
    } catch {
      // ignore – order will revert to last saved state after next load
    } finally {
      setLocalOrder(null);
    }
  }, [order, reloadSettings]);

  return (
    <nav ref={navRef} className="dock" onDoubleClick={() => setEditMode((m) => !m)}>
      {navItems.map(({ path, icon: Icon, label }, idx) => (
        <NavLink
          key={path}
          to={path}
          onClick={(e) => { if (editMode) e.preventDefault(); }}
          className={({ isActive }) =>
            ['dock-item', isActive && !editMode && 'active', editMode && 'jiggling']
              .filter(Boolean)
              .join(' ')
          }
          draggable={editMode}
          onDragStart={() => handleDragStart(idx)}
          onDragEnter={() => handleDragEnter(idx)}
          onDragEnd={handleDragEnd}
          onDragOver={(e) => e.preventDefault()}
          title={editMode ? `Drag to reorder — ${label}` : label}
        >
          <Icon size={22} strokeWidth={1.5} />
          <span>{label}</span>
        </NavLink>
      ))}

      {/* Grip button — toggles edit mode */}
      <button
        type="button"
        className={`dock-item dock-item--grip${editMode ? ' active' : ''}`}
        onClick={(e) => { e.stopPropagation(); setEditMode((m) => !m); }}
        title={editMode ? 'Done reordering (Esc)' : 'Reorder dock (or double-click)'}
      >
        <GripHorizontal size={22} strokeWidth={1.5} />
        <span>{editMode ? 'Done' : 'Order'}</span>
      </button>
    </nav>
  );
}

export default Dock;
