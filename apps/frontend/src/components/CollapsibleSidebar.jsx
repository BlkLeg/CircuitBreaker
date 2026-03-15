import React, { useState, useCallback } from 'react';
import PropTypes from 'prop-types';
import { NavLink } from 'react-router-dom';
import {
  BookOpen,
  Cloud,
  Cpu,
  HardDrive,
  Layers,
  Network,
  ScrollText,
  Server,
  Settings,
  Map,
  ScanSearch,
  Globe,
  MonitorCheck,
  RectangleHorizontal,
  Shield,
  Bell,
  Users,
  Webhook,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext.jsx';
import { useTranslation } from 'react-i18next';
import { canEdit, isAdmin } from '../utils/rbac';
import { useIsMobile } from '../hooks/useIsMobile';

const SIDEBAR_WIDTH_EXPANDED = 240;
const SIDEBAR_WIDTH_COLLAPSED = 60;

const NAV_ITEMS = [
  {
    group: 'Infrastructure',
    items: [
      { path: '/map', icon: Map, label: 'Map', labelKey: 'header.map' },
      { path: '/discovery', icon: ScanSearch, label: 'Discovery', labelKey: 'header.discovery' },
      { path: '/hardware', icon: Cpu, label: 'Hardware', labelKey: 'header.hardware' },
      { path: '/compute-units', icon: Server, label: 'Compute', labelKey: 'header.compute' },
      { path: '/services', icon: Layers, label: 'Services', labelKey: 'header.services' },
      { path: '/storage', icon: HardDrive, label: 'Storage', labelKey: 'header.storage' },
      { path: '/networks', icon: Network, label: 'Networks', labelKey: 'header.network' },
      { path: '/external-nodes', icon: Cloud, label: 'External', labelKey: 'header.external' },
      { path: '/ipam', icon: Globe, label: 'IPAM', labelKey: 'header.ipam', requireEditor: true },
      {
        path: '/racks',
        icon: RectangleHorizontal,
        label: 'Racks',
        labelKey: 'header.racks',
        requireEditor: true,
      },
      {
        path: '/status-pages',
        icon: MonitorCheck,
        label: 'Status Pages',
        labelKey: 'header.status',
        requireEditor: true,
      },
    ],
  },
  {
    group: 'Security',
    requireAdmin: true,
    items: [
      { path: '/certificates', icon: Shield, label: 'Certificates' },
      { path: '/notifications', icon: Bell, label: 'Notifications' },
      { path: '/webhooks', icon: Webhook, label: 'Webhooks' },
    ],
  },
  {
    group: 'Administration',
    items: [
      { path: '/tenants', icon: Users, label: 'Tenants', requireAdmin: true },
      {
        path: '/logs',
        icon: ScrollText,
        label: 'Logs',
        labelKey: 'header.logs',
        requireAdmin: true,
      },
      {
        path: '/settings',
        icon: Settings,
        label: 'Settings',
        labelKey: 'header.settings',
        requireEditor: true,
      },
      { path: '/docs', icon: BookOpen, label: 'Docs', labelKey: 'header.docs' },
    ],
  },
];

function CollapsibleSidebar({ pendingCount = 0, onToggle }) {
  const { t } = useTranslation('common');
  const { user } = useAuth();
  const isMobile = useIsMobile();
  const [collapsed, setCollapsed] = useState(false);

  const handleToggle = useCallback(() => {
    setCollapsed((prev) => {
      const next = !prev;
      if (onToggle) onToggle(next);
      return next;
    });
  }, [onToggle]);

  const filterItems = useCallback(
    (items) => {
      return items.filter((item) => {
        if (item.requireAdmin && !isAdmin(user)) return false;
        if (item.requireEditor && !canEdit(user)) return false;
        return true;
      });
    },
    [user]
  );

  if (isMobile) {
    return null;
  }

  const visibleGroups = NAV_ITEMS.map((group) => ({
    ...group,
    items: filterItems(group.items),
  })).filter((group) => {
    if (group.requireAdmin && !isAdmin(user)) return false;
    return group.items.length > 0;
  });

  return (
    <aside
      className="sidebar"
      style={{
        position: 'fixed',
        left: 0,
        top: 'var(--header-height)',
        bottom: 0,
        width: collapsed ? SIDEBAR_WIDTH_COLLAPSED : SIDEBAR_WIDTH_EXPANDED,
        background: 'var(--color-surface)',
        borderRight: '1px solid var(--color-border)',
        overflowY: 'auto',
        overflowX: 'hidden',
        transition: 'width 0.2s ease',
        zIndex: 100,
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <div
        style={{
          padding: collapsed ? '12px 8px' : '12px 16px',
          borderBottom: '1px solid var(--color-border)',
          display: 'flex',
          justifyContent: collapsed ? 'center' : 'flex-end',
        }}
      >
        <button
          className="btn btn-ghost"
          onClick={handleToggle}
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          style={{
            padding: '6px',
            minWidth: 'auto',
          }}
        >
          {collapsed ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}
        </button>
      </div>

      <nav style={{ flex: 1, padding: collapsed ? '8px 4px' : '12px 8px' }}>
        {visibleGroups.map((group) => (
          <div key={group.group} style={{ marginBottom: 20 }}>
            {!collapsed && (
              <div
                style={{
                  fontSize: 11,
                  fontWeight: 600,
                  textTransform: 'uppercase',
                  color: 'var(--color-text-muted)',
                  padding: '8px 12px 6px',
                  letterSpacing: '0.5px',
                }}
              >
                {group.group}
              </div>
            )}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              {group.items.map((item) => {
                const Icon = item.icon;
                const label = t(item.labelKey || '', { defaultValue: item.label });
                return (
                  <NavLink
                    key={item.path}
                    to={item.path}
                    className={({ isActive }) =>
                      [
                        'sidebar-item',
                        isActive && 'sidebar-item--active',
                        collapsed && 'sidebar-item--collapsed',
                      ]
                        .filter(Boolean)
                        .join(' ')
                    }
                    title={collapsed ? label : undefined}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: collapsed ? 0 : 12,
                      padding: collapsed ? '10px' : '10px 12px',
                      borderRadius: 6,
                      textDecoration: 'none',
                      color: 'var(--color-text)',
                      fontSize: 14,
                      fontWeight: 500,
                      transition: 'background 0.15s ease',
                      position: 'relative',
                      justifyContent: collapsed ? 'center' : 'flex-start',
                    }}
                  >
                    <span style={{ position: 'relative', display: 'inline-flex' }}>
                      <Icon size={20} strokeWidth={1.5} />
                      {item.path === '/discovery' && pendingCount > 0 && (
                        <span
                          style={{
                            position: 'absolute',
                            top: -6,
                            right: -6,
                            background: '#f59e0b',
                            color: '#000',
                            borderRadius: 10,
                            fontSize: 9,
                            fontWeight: 700,
                            padding: '0 5px',
                            lineHeight: '16px',
                            minWidth: 16,
                            textAlign: 'center',
                          }}
                        >
                          {pendingCount > 99 ? '99+' : pendingCount}
                        </span>
                      )}
                    </span>
                    {!collapsed && <span>{label}</span>}
                  </NavLink>
                );
              })}
            </div>
          </div>
        ))}
      </nav>
    </aside>
  );
}

CollapsibleSidebar.propTypes = {
  pendingCount: PropTypes.number,
  onToggle: PropTypes.func,
};

export default CollapsibleSidebar;
