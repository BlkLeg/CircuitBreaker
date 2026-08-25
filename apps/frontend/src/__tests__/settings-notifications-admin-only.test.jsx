import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import SettingsPage from '../pages/SettingsPage.jsx';

// The /notifications API surface is admin-only. A non-admin must not be shown
// the Notifications section inside the one tab they can still reach.
let mockUser = { role: 'admin', is_admin: true, email: 'admin@test.com' };

vi.mock('../api/client', () => {
  const mockClient = {
    get: vi.fn().mockResolvedValue({ data: [] }),
    post: vi.fn().mockResolvedValue({ data: {} }),
    put: vi.fn().mockResolvedValue({ data: {} }),
    patch: vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
  };
  return {
    default: mockClient,
    settingsApi: { get: vi.fn(), update: vi.fn() },
    adminApi: {
      getStats: vi.fn().mockResolvedValue({ data: {} }),
      export: vi.fn().mockResolvedValue({ data: {} }),
      clearLab: vi.fn().mockResolvedValue({}),
    },
    cveApi: {
      getStatus: vi.fn().mockResolvedValue({ data: {} }),
      status: vi.fn().mockResolvedValue({ data: {} }),
      triggerSync: vi.fn().mockResolvedValue({ data: {} }),
    },
  };
});

vi.mock('../api/discovery.js', () => ({
  syncDocker: vi.fn().mockResolvedValue({}),
  getDiscoveryStatus: vi.fn().mockResolvedValue({ data: {} }),
}));

const mockSearchParams = new URLSearchParams('tab=integrations');
const mockSetSearchParams = vi.fn();
const mockSearchParamsTuple = [mockSearchParams, mockSetSearchParams];
vi.mock('react-router-dom', () => ({
  useNavigate: () => vi.fn(),
  useParams: () => ({}),
  useLocation: () => ({ pathname: '/settings', search: '?tab=integrations' }),
  useSearchParams: () => mockSearchParamsTuple,
  Link: ({ children, ...props }) => React.createElement('a', props, children),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key, opts) => opts?.defaultValue || key,
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}));

const mockSettings = {
  theme: 'dark',
  environments: [],
  categories: [],
  locations: [],
  map_default_filters: '{}',
  docker_sync_enabled: false,
  docker_sync_interval_minutes: 5,
  language: 'en',
  timezone: 'UTC',
  api_base_url: '',
};
const mockReloadSettings = vi.fn();
const mockSettingsCtx = { settings: mockSettings, reloadSettings: mockReloadSettings };

vi.mock('../context/SettingsContext', () => ({
  useSettings: () => mockSettingsCtx,
}));

const mockLogin = vi.fn();
vi.mock('../context/AuthContext.jsx', () => ({
  useAuth: () => ({ user: mockUser, login: mockLogin }),
}));

const mockTimezoneCtx = { timezone: 'UTC', setTimezone: vi.fn() };
vi.mock('../context/TimezoneContext.jsx', () => ({
  useTimezone: () => mockTimezoneCtx,
}));

const mockToast = { success: vi.fn(), error: vi.fn(), warn: vi.fn(), info: vi.fn() };
vi.mock('../components/common/Toast', () => ({
  useToast: () => mockToast,
}));

const mockCaps = { caps: {} };
vi.mock('../hooks/useCapabilities.js', () => ({
  useCapabilities: () => mockCaps,
}));

vi.mock('../components/settings/IconLibraryManager', () => ({
  default: () => React.createElement('div', null, 'IconLibraryManager'),
}));
vi.mock('../components/settings/ListEditor', () => ({
  default: ({ label }) => React.createElement('div', null, label || 'ListEditor'),
}));
vi.mock('../components/settings/BrandingSettings', () => ({
  default: () => React.createElement('div', null, 'BrandingSettings'),
}));
vi.mock('../components/settings/ThemeSettings', () => ({
  default: () => React.createElement('div', null, 'ThemeSettings'),
}));
vi.mock('../components/settings/DockSettings', () => ({
  default: () => React.createElement('div', null, 'DockSettings'),
}));
vi.mock('../components/settings/SettingsNav', () => {
  const SETTINGS_TABS = [
    { id: 'general', label: 'General', description: 'General settings' },
    { id: 'integrations', label: 'Integrations', description: 'External integrations' },
  ];
  return {
    SETTINGS_TABS,
    default: () => React.createElement('nav', { 'data-testid': 'settings-nav' }),
  };
});
vi.mock('../components/settings/SettingsActionBar', () => ({
  default: () => React.createElement('div', null, 'SettingsActionBar'),
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
  default: () => React.createElement('div', null, 'DiscoverySettings'),
}));
vi.mock('../pages/KnowledgeBasePage.jsx', () => ({
  default: () => React.createElement('div', null, 'KnowledgeBasePage'),
}));
vi.mock('../pages/AdminUsersPage.jsx', () => ({
  default: () => React.createElement('div', null, 'AdminUsersPage'),
}));
vi.mock('../components/settings/VaultStatusPanel.jsx', () => ({
  default: () => React.createElement('div', null, 'VaultStatusPanel'),
}));
vi.mock('../components/settings/WebhooksManager.jsx', () => ({
  default: () => React.createElement('div', null, 'WebhooksManager'),
}));
vi.mock('../components/settings/NotificationsManager', () => ({
  default: () => React.createElement('div', { 'data-testid': 'notifications-manager' }),
}));
vi.mock('../components/settings/OAuthProvidersManager', () => ({
  default: () => React.createElement('div', null, 'OAuthProvidersManager'),
}));
vi.mock('../components/settings/IntegrationsManager', () => ({
  default: () => React.createElement('div', null, 'IntegrationsManager'),
}));
vi.mock('../components/opnsense/OpnsenseIntegrationSection.jsx', () => ({
  default: () => React.createElement('div', null, 'OpnsenseIntegrationSection'),
}));
vi.mock('../pages/settings/DeviceRolesSection.jsx', () => ({
  default: () => React.createElement('div', null, 'DeviceRolesSection'),
}));
vi.mock('../components/settings/DbStatusPanel.jsx', () => ({
  default: () => React.createElement('div', null, 'DbStatusPanel'),
}));
vi.mock('../components/settings/HostStatsPanel.jsx', () => ({
  default: () => React.createElement('div', null, 'HostStatsPanel'),
}));
vi.mock('../components/settings/BackupSettings.jsx', () => ({
  default: () => React.createElement('div', null, 'BackupSettings'),
}));

describe('Settings → Integrations → Notifications visibility', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUser = { role: 'admin', is_admin: true, email: 'admin@test.com' };
  });

  it('shows the Notifications section to an admin', async () => {
    render(<SettingsPage />);

    await waitFor(() => {
      expect(screen.getByTestId('notifications-manager')).toBeInTheDocument();
    });
    expect(screen.getByRole('heading', { name: /^Notifications$/ })).toBeInTheDocument();
  });

  it('does not show the Notifications section to an editor', async () => {
    mockUser = { role: 'editor', is_admin: false, email: 'editor@test.com' };

    render(<SettingsPage />);

    // The integrations tab is the one tab a non-admin can reach; it must render.
    await waitFor(() => {
      expect(screen.getByText('NATS Message Bus')).toBeInTheDocument();
    });

    expect(screen.queryByTestId('notifications-manager')).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: /^Notifications$/ })).not.toBeInTheDocument();
  });
});
