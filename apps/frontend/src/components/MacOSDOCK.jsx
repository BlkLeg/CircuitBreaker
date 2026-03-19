import React, { useMemo, useRef, useState, useEffect, useCallback } from 'react';
import PropTypes from 'prop-types';
import { NavLink, useLocation } from 'react-router-dom';
import { motion } from 'framer-motion';
import { useTranslation } from 'react-i18next';
import { useIsMobile } from '../hooks/useIsMobile';
import { NAV_MAP as ALL_NAV_MAP } from '../data/navigation';
import { useAuth } from '../context/AuthContext.jsx';
import { canEdit, isAdmin } from '../utils/rbac';

export const NAV_MAP = ALL_NAV_MAP;
export { DEFAULT_ORDER } from '../data/navigation';
const NAV_ENTRIES = Object.entries(NAV_MAP).map(([path, item]) => ({ path, ...item }));

const ORIGINAL_DOCK_ORDER = [
  '/discovery',
  '/map',
  '/hardware',
  '/compute-units',
  '/services',
  '/storage',
  '/networks',
  '/external-nodes',
  '/ipam',
  '/racks',
  '/status-pages',
  '/docs',
  '/logs',
  '/settings',
];

const MOBILE_DOCK_ITEMS = new Set(['/map', '/hardware', '/settings']);
const DOCK_TRIGGER_ZONE_PX = 100;
const DOCK_HIDE_DELAY_MS = 450;
const DOCK_HIT_BUFFER_PX = 12;

function getWsStatusClass(status) {
  if (status === 'connecting') return 'macos-dock-status--connecting';
  if (status === 'disconnected') return 'macos-dock-status--disconnected';
  return 'macos-dock-status--connected';
}

function findNavItem(path) {
  return NAV_ENTRIES.find((entry) => entry.path === path) || null;
}

function isActivePath(pathname, itemPath) {
  return pathname === itemPath || pathname.startsWith(`${itemPath}/`);
}

export default function MacOSDOCK({ pendingCount = 0, wsStatus = 'connected' }) {
  const { t } = useTranslation('common');
  const location = useLocation();
  const isMobile = useIsMobile();
  const { user } = useAuth();
  const [dockVisible, setDockVisible] = useState(true);
  const dockRef = useRef(null);
  const hideTimerRef = useRef(null);

  const showDock = useCallback(() => {
    if (hideTimerRef.current) {
      clearTimeout(hideTimerRef.current);
      hideTimerRef.current = null;
    }
    setDockVisible(true);
  }, []);

  const scheduleHideDock = useCallback(() => {
    if (isMobile || hideTimerRef.current) return;
    hideTimerRef.current = setTimeout(() => {
      hideTimerRef.current = null;
      setDockVisible(false);
    }, DOCK_HIDE_DELAY_MS);
  }, [isMobile]);

  useEffect(() => {
    if (isMobile) {
      setDockVisible(true);
      return undefined;
    }

    const handleMouseMove = (event) => {
      const inTriggerZone = event.clientY >= window.innerHeight - DOCK_TRIGGER_ZONE_PX;
      const rect = dockRef.current?.getBoundingClientRect();
      const overDock =
        !!rect &&
        event.clientX >= rect.left - DOCK_HIT_BUFFER_PX &&
        event.clientX <= rect.right + DOCK_HIT_BUFFER_PX &&
        event.clientY >= rect.top - DOCK_HIT_BUFFER_PX &&
        event.clientY <= rect.bottom + DOCK_HIT_BUFFER_PX;

      if (inTriggerZone || overDock) showDock();
      else scheduleHideDock();
    };

    document.addEventListener('mousemove', handleMouseMove, { passive: true });
    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      if (hideTimerRef.current) {
        clearTimeout(hideTimerRef.current);
        hideTimerRef.current = null;
      }
    };
  }, [isMobile, scheduleHideDock, showDock]);

  const dockItems = useMemo(() => {
    const allowEditor = canEdit(user);
    const allowAdmin = isAdmin(user);
    return ORIGINAL_DOCK_ORDER.filter((path) => {
      if (!findNavItem(path)) return false;
      if (
        (path === '/settings' ||
          path === '/ipam' ||
          path === '/racks' ||
          path === '/status-pages') &&
        !allowEditor
      ) {
        return false;
      }
      if (path === '/logs' && !allowAdmin) return false;
      return true;
    })
      .map((path) => {
        const navItem = findNavItem(path);
        if (!navItem) return null;
        return { ...navItem, id: path.replace('/', '') || 'root' };
      })
      .filter(Boolean);
  }, [user]);

  const visibleItems = useMemo(
    () => (isMobile ? dockItems.filter((item) => MOBILE_DOCK_ITEMS.has(item.path)) : dockItems),
    [dockItems, isMobile]
  );

  return (
    <div
      className={['macos-dock-root', !dockVisible && !isMobile && 'is-hidden']
        .filter(Boolean)
        .join(' ')}
      data-mobile={isMobile ? 'true' : 'false'}
    >
      <nav
        aria-label="MacOS dock"
        className="macos-dock-shelf"
        ref={dockRef}
        onMouseEnter={showDock}
        onMouseLeave={scheduleHideDock}
      >
        <div className="macos-dock-items">
          {visibleItems.map((item) => (
            <DockIcon
              key={item.id}
              item={item}
              label={t(item.labelKey, { defaultValue: item.label })}
              isActive={isActivePath(location.pathname, item.path)}
              pendingCount={item.id === 'discovery' ? pendingCount : 0}
              wsStatus={item.id === 'discovery' ? wsStatus : null}
              isMobile={isMobile}
            />
          ))}
        </div>
      </nav>
    </div>
  );
}

function DockIcon({ item, label, isActive, pendingCount = 0, wsStatus = 'connected', isMobile }) {
  const Icon = item.icon;

  return (
    <NavLink to={item.path} className="macos-dock-link">
      <motion.div
        whileTap={{ y: -6, scale: 1.1 }}
        transition={{ duration: 0.1, ease: 'easeOut' }}
        className={['macos-dock-icon', isActive && 'is-active', isMobile && 'is-mobile']
          .filter(Boolean)
          .join(' ')}
      >
        <Icon size={isMobile ? 20 : 22} className="macos-dock-icon-glyph" />
        {pendingCount > 0 && (
          <span className="macos-dock-badge">{pendingCount > 99 ? '99+' : pendingCount}</span>
        )}

        {wsStatus && wsStatus !== 'connected' && (
          <span className={['macos-dock-status', getWsStatusClass(wsStatus)].join(' ')} />
        )}
      </motion.div>

      {isActive && <span className="macos-dock-active-indicator" />}

      {isMobile && <span className="macos-dock-mobile-label">{label}</span>}

      {!isMobile && <span className="macos-dock-tooltip">{label}</span>}
    </NavLink>
  );
}

DockIcon.propTypes = {
  item: PropTypes.shape({
    path: PropTypes.string.isRequired,
    icon: PropTypes.elementType.isRequired,
  }).isRequired,
  label: PropTypes.string.isRequired,
  isActive: PropTypes.bool.isRequired,
  pendingCount: PropTypes.number,
  wsStatus: PropTypes.string,
  isMobile: PropTypes.bool.isRequired,
};

MacOSDOCK.propTypes = {
  pendingCount: PropTypes.number,
  wsStatus: PropTypes.string,
};
