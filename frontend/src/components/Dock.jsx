import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { NavLink } from 'react-router-dom';
import { BookOpen, Cloud, Cpu, GripHorizontal, HardDrive, Layers, Network, ScrollText, Server, Settings, Map, ScanSearch } from 'lucide-react';
import { settingsApi } from '../api/client';
import { useSettings } from '../context/SettingsContext';
import { useIsMobile } from '../hooks/useIsMobile';
import MobileTabBar from './MobileTabBar';
import { useTranslation } from 'react-i18next';

export const NAV_MAP = {
  '/hardware':      { icon: Cpu,        label: 'Hardware', labelKey: 'header.hardware'   },
  '/compute-units': { icon: Server,     label: 'Compute', labelKey: 'header.compute'     },
  '/services':      { icon: Layers,     label: 'Services', labelKey: 'header.services'   },
  '/networks':      { icon: Network,    label: 'Network', labelKey: 'header.network'     },
  '/external-nodes':{ icon: Cloud,      label: 'External', labelKey: 'header.external'   },
  '/storage':       { icon: HardDrive,  label: 'Storage', labelKey: 'header.storage'     },
  '/map':           { icon: Map,        label: 'Map', labelKey: 'header.map'             },
  '/discovery':     { icon: ScanSearch, label: 'Discovery', labelKey: 'header.discovery' },
  '/docs':          { icon: BookOpen,   label: 'Docs', labelKey: 'header.docs'           },
  '/logs':          { icon: ScrollText, label: 'Logs', labelKey: 'header.logs'           },
  '/settings':      { icon: Settings,   label: 'Settings', labelKey: 'header.settings'   },
};

export const DEFAULT_ORDER = [
  '/map',
  '/hardware',
  '/compute-units',
  '/services',
  '/networks',
  '/external-nodes',
  '/storage',
  '/discovery',
  '/docs',
  '/logs',
  '/settings',
];

function Dock({ pendingCount = 0 }) {
  const { t } = useTranslation('common');
  const isMobile = useIsMobile();
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
  const order = useMemo(() => (
    savedOrder
      ? [
          ...savedOrder.filter((p) => NAV_MAP[p]),
          ...DEFAULT_ORDER.filter((p) => NAV_MAP[p] && !savedOrder.includes(p)),
        ]
      : DEFAULT_ORDER
  ), [savedOrder]);

  const hiddenItems = new Set(settings?.dock_hidden_items ?? []);
  const navItems = order
    .filter((path) => NAV_MAP[path] && !hiddenItems.has(path))
    .map((path) => {
      const item = NAV_MAP[path];
      return {
        path,
        ...item,
        label: t(item.labelKey || '', { defaultValue: item.label }),
      };
    });

  // Mobile navigation prep
  const mobilePrimaryPaths = new Set(['/map', '/hardware', '/services', '/networks']);
  const overflowItems = navItems.filter(item => !mobilePrimaryPaths.has(item.path));

  /* ── Horizontal scroll ───────────────────────────────── */
  useEffect(() => {
    const el = navRef.current;
    if (!el || isMobile) return;
    const onWheel = (e) => {
      if (e.deltaY === 0) return;
      e.preventDefault();
      el.scrollLeft += e.deltaY;
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [isMobile]);

  /* ── Exit edit mode on Escape ────────────────────────── */
  useEffect(() => {
    if (!editMode) return;
    const handler = (e) => { if (e.key === 'Escape') setEditMode(false); };
    globalThis.addEventListener('keydown', handler);
    return () => globalThis.removeEventListener('keydown', handler);
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

  if (isMobile) {
    return <MobileTabBar overflowItems={overflowItems} pendingCount={pendingCount} />;
  }

  return (
    <nav aria-label="Main Navigation" ref={navRef} className="dock" onDoubleClick={() => setEditMode((m) => !m)}>
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
          aria-label={label}
        >
          <span style={{ position: 'relative', display: 'inline-flex' }}>
            <Icon size={22} strokeWidth={1.5} />
            {path === '/discovery' && pendingCount > 0 && (
              <span style={{
                position: 'absolute', top: -5, right: -7,
                background: '#f59e0b', color: '#000',
                borderRadius: 9, fontSize: 9, fontWeight: 700,
                padding: '0 4px', lineHeight: '16px', minWidth: 16, textAlign: 'center',
              }}>
                {pendingCount > 99 ? '99+' : pendingCount}
              </span>
            )}
          </span>
          <span>{label}</span>
        </NavLink>
      ))}

      {/* Grip button — toggles edit mode */}
      <button
        type="button"
        className={`dock-item dock-item--grip${editMode ? ' active' : ''}`}
        onClick={(e) => { e.stopPropagation(); setEditMode((m) => !m); }}
        title={editMode ? 'Done reordering (Esc)' : 'Reorder dock (or double-click)'}
        aria-label={editMode ? 'Done reordering dock' : 'Reorder dock'}
      >
        <GripHorizontal size={22} strokeWidth={1.5} />
        <span>{editMode ? 'Done' : 'Order'}</span>
      </button>
    </nav>
  );
}

Dock.propTypes = {
  pendingCount: PropTypes.number,
};

export default Dock;
