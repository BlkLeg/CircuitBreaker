import React from 'react';
import PropTypes from 'prop-types';
import {
  Settings,
  Palette,
  Layers,
  Globe,
  ShieldCheck,
  Database,
  Search,
  X,
  Plug,
  Users,
  Webhook,
} from 'lucide-react';

export const SETTINGS_TABS = [
  {
    id: 'general',
    label: 'General',
    icon: Settings,
    description: 'Basic app configuration and defaults.',
  },
  {
    id: 'appearance',
    label: 'Appearance',
    icon: Palette,
    description: 'Themes, branding, and visual preferences.',
  },
  {
    id: 'resources',
    label: 'Resources',
    icon: Layers,
    description: 'Manage environments, categories, and locations.',
  },
  {
    id: 'connectivity',
    label: 'Connectivity',
    icon: Globe,
    description: 'Auto-discovery and API settings.',
  },
  {
    id: 'integrations',
    label: 'Integrations',
    icon: Plug,
    description: 'NATS, Docker, and external service controls.',
  },
  {
    id: 'webhooks',
    label: 'Webhooks',
    icon: Webhook,
    description: 'Webhook endpoints, event routing, and delivery logs.',
  },
  {
    id: 'security',
    label: 'Security',
    icon: ShieldCheck,
    description: 'Authentication and session management.',
  },
  {
    id: 'users',
    label: 'Users',
    icon: Users,
    description: 'Manage accounts, roles, invites, and sessions.',
    adminOnly: true,
  },
  {
    id: 'system',
    label: 'System',
    icon: Database,
    description: 'Backups, maintenance, and advanced tools.',
  },
];

const S = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
    padding: '12px',
    gap: '20px',
  },
  searchContainer: {
    position: 'relative',
    marginBottom: '8px',
  },
  searchInput: {
    width: '100%',
    padding: '10px 12px 10px 36px',
    fontSize: '13px',
    borderRadius: '8px',
    background: 'var(--color-bg)',
    border: '1px solid var(--color-border)',
    color: 'var(--color-text)',
    outline: 'none',
    transition: 'border-color 0.2s',
  },
  searchIcon: {
    position: 'absolute',
    left: '10px',
    top: '50%',
    transform: 'translateY(-50%)',
    color: 'var(--color-text-muted)',
    pointerEvents: 'none',
  },
  clearSearch: {
    position: 'absolute',
    right: '10px',
    top: '50%',
    transform: 'translateY(-50%)',
    color: 'var(--color-text-muted)',
    cursor: 'pointer',
    background: 'none',
    border: 'none',
    padding: '4px',
    display: 'flex',
    alignItems: 'center',
  },
  nav: {
    display: 'flex',
    flexDirection: 'column',
    gap: '4px',
  },
  tab: (active) => ({
    display: 'flex',
    alignItems: 'center',
    gap: '12px',
    padding: '10px 14px',
    borderRadius: '8px',
    fontSize: '13px',
    fontWeight: 500,
    color: active ? 'var(--color-primary)' : 'var(--color-text-muted)',
    background: active ? 'var(--color-glow)' : 'transparent',
    border: '1px solid',
    borderColor: active ? 'var(--color-primary)' : 'transparent',
    cursor: 'pointer',
    textAlign: 'left',
    transition: 'all 0.2s',
    width: '100%',
  }),
  tabIcon: (active) => ({
    color: active ? 'var(--color-primary)' : 'var(--color-text-muted)',
    flexShrink: 0,
  }),
};

export default function SettingsNav({
  activeTab,
  onTabChange,
  searchQuery,
  onSearchChange,
  tabs,
  isAdmin,
}) {
  const visibleTabs = (tabs || SETTINGS_TABS).filter((t) => !t.adminOnly || isAdmin);

  return (
    <div style={S.container}>
      <div style={S.searchContainer}>
        <Search size={16} style={S.searchIcon} />
        <input
          type="text"
          placeholder="Search settings..."
          style={S.searchInput}
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
        />
        {searchQuery && (
          <button style={S.clearSearch} onClick={() => onSearchChange('')}>
            <X size={14} />
          </button>
        )}
      </div>

      <nav style={S.nav}>
        {visibleTabs.map((tab) => (
          <button
            key={tab.id}
            style={S.tab(activeTab === tab.id)}
            onClick={() => onTabChange(tab.id)}
          >
            <tab.icon size={18} style={S.tabIcon(activeTab === tab.id)} />
            {tab.label}
          </button>
        ))}
      </nav>
    </div>
  );
}

SettingsNav.propTypes = {
  activeTab: PropTypes.string.isRequired,
  onTabChange: PropTypes.func.isRequired,
  searchQuery: PropTypes.string.isRequired,
  onSearchChange: PropTypes.func.isRequired,
  tabs: PropTypes.array,
  isAdmin: PropTypes.bool,
};
