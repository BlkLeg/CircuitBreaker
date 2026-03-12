import { describe, it, vi, expect } from 'vitest';
import { render } from '@testing-library/react';
import React from 'react';

vi.mock('../api/client', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  settingsApi: { get: vi.fn(), update: vi.fn() },
  adminApi: {
    getStats: vi.fn().mockResolvedValue({ data: {} }),
    export: vi.fn(),
    clearLab: vi.fn(),
  },
  cveApi: { status: vi.fn().mockResolvedValue({ data: {} }), triggerSync: vi.fn() },
  hardwareApi: { list: vi.fn().mockResolvedValue({ data: [] }) },
  computeUnitsApi: { list: vi.fn().mockResolvedValue({ data: [] }) },
  servicesApi: { list: vi.fn().mockResolvedValue({ data: [] }) },
  networksApi: { list: vi.fn().mockResolvedValue({ data: [] }) },
  graphApi: { get: vi.fn().mockResolvedValue({ data: {} }) },
  searchApi: { search: vi.fn() },
  environmentsApi: { list: vi.fn().mockResolvedValue({ data: [] }) },
  tagsApi: { list: vi.fn().mockResolvedValue({ data: [] }) },
  categoriesApi: { list: vi.fn().mockResolvedValue({ data: [] }) },
  capabilitiesApi: { get: vi.fn().mockResolvedValue({ data: {} }) },
  proxmoxApi: { list: vi.fn().mockResolvedValue({ data: [] }) },
  systemApi: { getStats: vi.fn().mockResolvedValue({ data: {} }) },
  usersApi: { me: vi.fn().mockResolvedValue({ data: {} }) },
  clustersApi: { list: vi.fn().mockResolvedValue({ data: [] }) },
  storageApi: { list: vi.fn().mockResolvedValue({ data: [] }) },
  miscApi: { list: vi.fn().mockResolvedValue({ data: [] }) },
  externalNodesApi: { list: vi.fn().mockResolvedValue({ data: [] }) },
  logsApi: { list: vi.fn().mockResolvedValue({ data: [] }) },
  catalogApi: { search: vi.fn().mockResolvedValue({ data: [] }) },
  telemetryApi: { list: vi.fn().mockResolvedValue({ data: [] }) },
  ipCheckApi: { check: vi.fn().mockResolvedValue({ data: {} }) },
  adminUsersApi: { list: vi.fn().mockResolvedValue({ data: [] }) },
  docsApi: { list: vi.fn().mockResolvedValue({ data: [] }) },
}));
vi.mock('../api/discovery.js', () => ({ syncDocker: vi.fn(), getDiscoveryStatus: vi.fn() }));

const mockSetSearchParams = vi.fn();
const mockSearchParams = new URLSearchParams();
vi.mock('react-router-dom', () => ({
  useNavigate: () => vi.fn(),
  useParams: () => ({}),
  useLocation: () => ({ pathname: '/settings', search: '' }),
  useSearchParams: () => [mockSearchParams, mockSetSearchParams],
  Link: ({ children, ...p }) => React.createElement('a', p, children),
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (k, opts) => opts?.defaultValue || k,
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}));
vi.mock('../context/SettingsContext', () => ({
  useSettings: () => ({
    settings: { theme: 'dark', environments: [], categories: [], locations: [] },
    reloadSettings: vi.fn(),
  }),
}));
vi.mock('../context/AuthContext.jsx', () => ({
  useAuth: () => ({ user: { role: 'admin', is_admin: true }, login: vi.fn() }),
}));
vi.mock('../context/TimezoneContext.jsx', () => ({
  useTimezone: () => ({ timezone: 'UTC', setTimezone: vi.fn() }),
}));
vi.mock('../components/common/Toast', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn(), warn: vi.fn(), info: vi.fn() }),
}));
vi.mock('../hooks/useCapabilities.js', () => ({ useCapabilities: () => ({ caps: {} }) }));

// Mock ALL sub-components to prevent heavy renders
vi.mock('../components/settings/IconLibraryManager', () => ({
  default: () => React.createElement('div', null, 'IconLib'),
}));
vi.mock('../components/settings/ListEditor', () => ({
  default: () => React.createElement('div', null, 'ListEditor'),
}));
vi.mock('../components/settings/BrandingSettings', () => ({
  default: () => React.createElement('div', null, 'Branding'),
}));
vi.mock('../components/settings/ThemeSettings', () => ({
  default: () => React.createElement('div', null, 'Theme'),
}));
vi.mock('../components/settings/DockSettings', () => ({
  default: () => React.createElement('div', null, 'Dock'),
}));
vi.mock('../components/settings/SettingsNav', () => {
  const SETTINGS_TABS = [
    { id: 'general', label: 'General', description: 'General settings' },
    { id: 'appearance', label: 'Appearance', description: 'Visual settings' },
    { id: 'security', label: 'Security', description: 'Auth settings' },
  ];
  return {
    SETTINGS_TABS,
    default: ({ activeTab, onTabChange, tabs }) =>
      React.createElement(
        'nav',
        { 'data-testid': 'settings-nav' },
        (tabs || SETTINGS_TABS).map((tab) =>
          React.createElement(
            'button',
            { key: tab.id, onClick: () => onTabChange(tab.id) },
            tab.label
          )
        )
      ),
  };
});
vi.mock('../components/settings/SettingsActionBar', () => ({
  default: () => React.createElement('div', null, 'ActionBar'),
}));
vi.mock('../components/settings/SettingField', () => ({
  default: ({ label, children }) =>
    React.createElement('div', null, React.createElement('label', null, label), children),
}));
vi.mock('../components/settings/SettingSection', () => ({
  default: ({ title, children }) =>
    React.createElement('section', null, React.createElement('h3', null, title), children),
}));
vi.mock('../components/common/ConfirmDialog', () => ({ default: () => null }));
vi.mock('../components/common/ClearLabDialog', () => ({ default: () => null }));
vi.mock('../components/auth/FirstUserDialog', () => ({ default: () => null }));
vi.mock('../components/TimezoneSelect.jsx', () => ({
  default: () => React.createElement('select', null),
}));
vi.mock('../pages/settings/DiscoverySettingsPage.jsx', () => ({
  default: () => React.createElement('div', null, 'Discovery'),
}));
vi.mock('../pages/AdminUsersPage.jsx', () => ({
  default: () => React.createElement('div', null, 'AdminUsers'),
}));
vi.mock('../components/settings/VaultStatusPanel.jsx', () => ({
  default: () => React.createElement('div', null, 'Vault'),
}));
vi.mock('../components/settings/DbStatusPanel.jsx', () => ({
  default: () => React.createElement('div', null, 'DbStatus'),
}));
vi.mock('../components/settings/HostStatsPanel.jsx', () => ({
  default: () => React.createElement('div', null, 'HostStats'),
}));
vi.mock('../components/settings/WebhooksManager.jsx', () => ({
  default: () => React.createElement('div', null, 'Webhooks'),
}));
vi.mock('../components/settings/NotificationsManager.jsx', () => ({
  default: () => React.createElement('div', null, 'Notifications'),
}));

describe('SettingsPage render debug', () => {
  it('can render SettingsPage', async () => {
    const { default: SettingsPage } = await import('../pages/SettingsPage.jsx');
    const { container } = render(<SettingsPage />);
    expect(container).toBeTruthy();
  });
});
