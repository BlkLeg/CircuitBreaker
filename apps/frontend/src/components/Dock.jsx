/* eslint-disable security/detect-object-injection */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { NavLink, useLocation } from 'react-router-dom';
import {
  BookOpen,
  Cloud,
  Cpu,
  GripHorizontal,
  HardDrive,
  Layers,
  Network,
  ScrollText,
  Server,
  Settings,
  Map,
  ScanSearch,
} from 'lucide-react';
import { settingsApi } from '../api/client';
import { useAuth } from '../context/AuthContext.jsx';
import { useSettings } from '../context/SettingsContext';
import { useIsMobile } from '../hooks/useIsMobile';
import MobileTabBar from './MobileTabBar';
import { useTranslation } from 'react-i18next';
import { canEdit, isAdmin } from '../utils/rbac';

export const NAV_MAP = {
  '/hardware': { icon: Cpu, label: 'Hardware', labelKey: 'header.hardware' },
  '/compute-units': { icon: Server, label: 'Compute', labelKey: 'header.compute' },
  '/services': { icon: Layers, label: 'Services', labelKey: 'header.services' },
  '/networks': { icon: Network, label: 'Network', labelKey: 'header.network' },
  '/external-nodes': { icon: Cloud, label: 'External', labelKey: 'header.external' },
  '/storage': { icon: HardDrive, label: 'Storage', labelKey: 'header.storage' },
  '/map': { icon: Map, label: 'Map', labelKey: 'header.map' },
  '/discovery': { icon: ScanSearch, label: 'Discovery', labelKey: 'header.discovery' },
  '/docs': { icon: BookOpen, label: 'Docs', labelKey: 'header.docs' },
  '/logs': { icon: ScrollText, label: 'Logs', labelKey: 'header.logs' },
  '/settings': { icon: Settings, label: 'Settings', labelKey: 'header.settings' },
};

export const DEFAULT_ORDER = [
  '/discovery',
  '/map',
  '/hardware',
  '/compute-units',
  '/services',
  '/storage',
  '/networks',
  '/external-nodes',
  '/docs',
  '/logs',
  '/settings',
];

/* ── Magnification constants ─────────────────────────────────────────── */
const MAX_SCALE = 1.7; // peak scale on direct hover
const SIGMA = 80; // gaussian falloff radius in px (how wide the wave is)
const ICON_SIZE = 22; // icon size passed to lucide

/* ── Auto-hide constants ─────────────────────────────────────────────── */
const DOCK_TRIGGER_ZONE_PX = 100; // show dock when mouse within this many px of bottom
const DOCK_HIDE_DELAY_MS = 500;

function gaussian(dist) {
  return 1 + (MAX_SCALE - 1) * Math.exp(-(dist * dist) / (2 * SIGMA * SIGMA));
}

const WS_STATUS_COLORS = { connected: '#2ecc71', connecting: '#f59e0b', disconnected: '#e74c3c' };

function Dock({ pendingCount = 0, wsStatus = 'connected' }) {
  const { t } = useTranslation('common');
  const isMobile = useIsMobile();
  const { user } = useAuth();
  const navRef = useRef(null);
  const itemRefs = useRef([]); // refs to each .dock-item wrapper
  const dragItem = useRef(null);
  const dragOver = useRef(null);

  const { pathname } = useLocation();
  const { settings, reloadSettings } = useSettings();
  const [editMode, setEditMode] = useState(false);
  const [scales, setScales] = useState([]); // per-item scale values
  // localOrder is set optimistically during a drag; cleared after save
  const [localOrder, setLocalOrder] = useState(null);

  // Auto-hide: dock visible when mouse is near bottom or over the dock
  const [dockVisible, setDockVisible] = useState(true);
  const hideDockTimeoutRef = useRef(null);

  /* ── Order resolution ────────────────────────────────────────────── */
  const savedOrder =
    localOrder ??
    (Array.isArray(settings?.dock_order) && settings.dock_order.length > 0
      ? settings.dock_order
      : null);
  const order = useMemo(
    () =>
      savedOrder
        ? [
            ...savedOrder.filter((p) => NAV_MAP[p]),
            ...DEFAULT_ORDER.filter((p) => NAV_MAP[p] && !savedOrder.includes(p)),
          ]
        : DEFAULT_ORDER,
    [savedOrder]
  );

  const hiddenItems = new Set(settings?.dock_hidden_items ?? []);
  const allowSettings = canEdit(user);
  const allowLogs = isAdmin(user);
  const navItems = order
    .filter((path) => {
      if (!NAV_MAP[path] || hiddenItems.has(path)) return false;
      if (path === '/settings' && !allowSettings) return false;
      if (path === '/logs' && !allowLogs) return false;
      return true;
    })
    .map((path) => {
      const item = NAV_MAP[path];
      return {
        path,
        ...item,
        label: t(item.labelKey || '', { defaultValue: item.label }),
      };
    });

  // Keep scales array length in sync with navItems
  useEffect(() => {
    setScales(new Array(navItems.length + 1).fill(1)); // +1 for grip
  }, [navItems.length]);

  /* ── Mobile ──────────────────────────────────────────────────────── */
  const mobilePrimaryPaths = new Set(['/map', '/hardware', '/services', '/networks']);
  const overflowItems = navItems.filter((item) => !mobilePrimaryPaths.has(item.path));

  /* ── Magnification — mousemove on dock ───────────────────────────── */
  const handleMouseMove = useCallback(
    (e) => {
      if (editMode) return;
      const mouseX = e.clientX;
      const next = itemRefs.current.map((el) => {
        if (!el) return 1;
        const rect = el.getBoundingClientRect();
        const centerX = rect.left + rect.width / 2;
        return gaussian(Math.abs(mouseX - centerX));
      });
      setScales(next);
    },
    [editMode]
  );

  const handleMouseLeave = useCallback(() => {
    setScales((prev) => prev.map(() => 1));
  }, []);

  /* ── Auto-hide: show when mouse near bottom or over dock; hide after delay when away ── */
  const scheduleHideDock = useCallback(() => {
    if (hideDockTimeoutRef.current) return;
    hideDockTimeoutRef.current = setTimeout(() => {
      hideDockTimeoutRef.current = null;
      setDockVisible(false);
    }, DOCK_HIDE_DELAY_MS);
  }, []);

  const showDock = useCallback(() => {
    if (hideDockTimeoutRef.current) {
      clearTimeout(hideDockTimeoutRef.current);
      hideDockTimeoutRef.current = null;
    }
    setDockVisible(true);
  }, []);

  useEffect(() => {
    const onMouseMove = (e) => {
      const inTriggerZone = e.clientY >= window.innerHeight - DOCK_TRIGGER_ZONE_PX;
      const overDock =
        navRef.current &&
        (() => {
          const r = navRef.current.getBoundingClientRect();
          return (
            e.clientX >= r.left &&
            e.clientX <= r.right &&
            e.clientY >= r.top &&
            e.clientY <= r.bottom
          );
        })();
      if (inTriggerZone || overDock) showDock();
      else scheduleHideDock();
    };
    document.addEventListener('mousemove', onMouseMove, { passive: true });
    return () => document.removeEventListener('mousemove', onMouseMove);
  }, [showDock, scheduleHideDock]);

  useEffect(() => {
    return () => {
      if (hideDockTimeoutRef.current) {
        clearTimeout(hideDockTimeoutRef.current);
        hideDockTimeoutRef.current = null;
      }
    };
  }, []);

  const handleDockMouseEnter = useCallback(() => {
    showDock();
  }, [showDock]);

  const handleDockMouseLeave = useCallback(() => {
    scheduleHideDock();
  }, [scheduleHideDock]);

  /* ── Exit edit mode on Escape / outside click ────────────────────── */
  useEffect(() => {
    if (!editMode) return;
    const onKey = (e) => {
      if (e.key === 'Escape') setEditMode(false);
    };
    globalThis.addEventListener('keydown', onKey);
    return () => globalThis.removeEventListener('keydown', onKey);
  }, [editMode]);

  useEffect(() => {
    if (!editMode) return;
    const onDown = (e) => {
      if (navRef.current && !navRef.current.contains(e.target)) setEditMode(false);
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [editMode]);

  /* ── Drag handlers ───────────────────────────────────────────────── */
  const handleDragStart = (idx) => {
    dragItem.current = idx;
  };
  const handleDragEnter = (idx) => {
    dragOver.current = idx;
  };

  const handleDragEnd = useCallback(async () => {
    const from = dragItem.current;
    const to = dragOver.current;
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
      // revert to last saved on error
    } finally {
      setLocalOrder(null);
    }
  }, [order, reloadSettings]);

  if (isMobile) {
    return <MobileTabBar overflowItems={overflowItems} pendingCount={pendingCount} />;
  }

  return (
    <nav
      aria-label="Main Navigation"
      ref={navRef}
      className={['dock', !dockVisible && 'dock--autohide-hidden'].filter(Boolean).join(' ')}
      onMouseMove={handleMouseMove}
      onMouseEnter={handleDockMouseEnter}
      onMouseLeave={(e) => {
        handleMouseLeave(e);
        handleDockMouseLeave();
      }}
      onDoubleClick={() => setEditMode((m) => !m)}
    >
      {navItems.map(({ path, icon: Icon, label }, idx) => (
        <NavLink
          key={path}
          to={path}
          ref={(el) => {
            itemRefs.current[idx] = el;
          }}
          onClick={(e) => {
            if (editMode) e.preventDefault();
          }}
          className={({ isActive }) =>
            ['dock-item', isActive && !editMode && 'active', editMode && 'jiggling']
              .filter(Boolean)
              .join(' ')
          }
          style={{ '--dock-scale': scales[idx] ?? 1 }}
          draggable={editMode}
          onDragStart={() => handleDragStart(idx)}
          onDragEnter={() => handleDragEnter(idx)}
          onDragEnd={handleDragEnd}
          onDragOver={(e) => e.preventDefault()}
          title={editMode ? `Drag to reorder — ${label}` : undefined}
          aria-label={label}
        >
          {/* Icon with optional pending badge */}
          <span style={{ position: 'relative', display: 'inline-flex' }}>
            <Icon size={ICON_SIZE} strokeWidth={1.5} />
            {path === '/discovery' && pendingCount > 0 && (
              <span
                style={{
                  position: 'absolute',
                  top: -5,
                  right: -7,
                  background: '#f59e0b',
                  color: '#000',
                  borderRadius: 9,
                  fontSize: 9,
                  fontWeight: 700,
                  padding: '0 4px',
                  lineHeight: '16px',
                  minWidth: 16,
                  textAlign: 'center',
                }}
              >
                {pendingCount > 99 ? '99+' : pendingCount}
              </span>
            )}
            {path === '/discovery' && wsStatus !== 'connected' && (
              <span
                title={wsStatus === 'connecting' ? 'Reconnecting…' : 'Disconnected'}
                style={{
                  position: 'absolute',
                  bottom: -3,
                  right: -3,
                  width: 7,
                  height: 7,
                  borderRadius: '50%',
                  background: WS_STATUS_COLORS[wsStatus] ?? WS_STATUS_COLORS.disconnected,
                  border: '1px solid var(--color-bg, #111)',
                }}
              />
            )}
          </span>

          {/* Active indicator dot */}
          {pathname === path && !editMode && (
            <span className="dock-active-dot" aria-hidden="true" />
          )}

          {/* Hover tooltip */}
          <span className="dock-tooltip">{label}</span>
        </NavLink>
      ))}

      {/* Grip button — toggles edit mode */}
      <button
        type="button"
        ref={(el) => {
          itemRefs.current[navItems.length] = el;
        }}
        className={`dock-item dock-item--grip${editMode ? ' active' : ''}`}
        style={{ '--dock-scale': scales[navItems.length] ?? 1 }}
        onClick={(e) => {
          e.stopPropagation();
          setEditMode((m) => !m);
        }}
        title={editMode ? 'Done reordering (Esc)' : 'Reorder dock (or double-click)'}
        aria-label={editMode ? 'Done reordering dock' : 'Reorder dock'}
      >
        <GripHorizontal size={ICON_SIZE} strokeWidth={1.5} />
        <span className="dock-tooltip">{editMode ? 'Done' : 'Order'}</span>
      </button>
    </nav>
  );
}

Dock.propTypes = {
  pendingCount: PropTypes.number,
  wsStatus: PropTypes.oneOf(['connected', 'connecting', 'disconnected']),
};

export default Dock;
