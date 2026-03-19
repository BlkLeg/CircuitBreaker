import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import SettingsPage from '../pages/SettingsPage.jsx';

// Mock api client
vi.mock('../api/client', () => {
  const mockClient = {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  };
  return {
    default: mockClient,
    settingsApi: {
      get: vi.fn(),
      update: vi.fn(),
    },
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
  };
});

vi.mock('../api/discovery.js', () => ({
  syncDocker: vi.fn().mockResolvedValue({}),
  getDiscoveryStatus: vi.fn().mockResolvedValue({ data: {} }),
}));

const mockSetSearchParams = vi.fn();
const mockSearchParams = new URLSearchParams();
vi.mock('react-router-dom', () => ({
  useNavigate: () => vi.fn(),
  useParams: () => ({}),
  useLocation: () => ({ pathname: '/settings', search: '' }),
  useSearchParams: () => [mockSearchParams, mockSetSearchParams],
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
  default_environment: '',
  vendor_icon_mode: 'custom_files',
  show_experimental_features: false,
  show_page_hints: true,
  api_base_url: '',
  environments: ['prod', 'staging', 'dev'],
  categories: [],
  locations: ['Rack A'],
  auth_enabled: true,
  registration_open: true,
  rate_limit_profile: 'normal',
  session_timeout_hours: 24,
  show_external_nodes_on_map: true,
  show_header_widgets: true,
  show_time_widget: true,
  show_weather_widget: true,
  weather_location: 'Phoenix, AZ',
  timezone: 'UTC',
  language: 'en',
  listener_enabled: false,
  mdns_enabled: true,
  ssdp_enabled: true,
  arp_enabled: true,
  tcp_probe_enabled: true,
  prober_interval_minutes: 15,
  deep_dive_max_parallel: 5,
  scan_aggressiveness: 'normal',
  graph_default_layout: 'dagre',
  map_title: 'Topology',
  map_default_filters: '{}',
  docker_sync_enabled: false,
  docker_sync_interval_minutes: 5,
  realtime_notifications_enabled: true,
  realtime_transport: 'auto',
  cve_sync_enabled: false,
  cve_sync_interval_hours: 24,
  audit_log_retention_days: 90,
  concurrent_sessions: 5,
  login_lockout_attempts: 5,
  login_lockout_minutes: 15,
  invite_expiry_days: 7,
  masquerade_enabled: true,
};

vi.mock('../context/SettingsContext', () => ({
  useSettings: () => ({
    settings: mockSettings,
    reloadSettings: vi.fn(),
  }),
}));

vi.mock('../context/AuthContext.jsx', () => ({
  useAuth: () => ({
    user: { role: 'admin', is_admin: true, email: 'admin@test.com' },
    login: vi.fn(),
  }),
}));

vi.mock('../context/TimezoneContext.jsx', () => ({
  useTimezone: () => ({
    timezone: 'UTC',
    setTimezone: vi.fn(),
  }),
}));

vi.mock('../components/common/Toast', () => ({
  useToast: () => ({
    success: vi.fn(),
    error: vi.fn(),
    warn: vi.fn(),
    info: vi.fn(),
  }),
}));

vi.mock('../hooks/useCapabilities.js', () => ({
  useCapabilities: () => ({ caps: {} }),
}));

// Mock heavy sub-components to avoid deep dependency chains
vi.mock('../components/settings/IconLibraryManager', () => ({
  default: () =>
    React.createElement('div', { 'data-testid': 'icon-library-manager' }, 'IconLibraryManager'),
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
    { id: 'appearance', label: 'Appearance', description: 'Visual settings' },
    { id: 'security', label: 'Security', description: 'Auth settings' },
    { id: 'integrations', label: 'Integrations', description: 'External integrations' },
    { id: 'webhooks', label: 'Webhooks', description: 'Webhook configuration' },
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
            {
              key: tab.id,
              onClick: () => onTabChange(tab.id),
              className: activeTab === tab.id ? 'active' : '',
            },
            tab.label
          )
        )
      ),
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
vi.mock('../components/common/ConfirmDialog', () => ({
  default: () => null,
}));
vi.mock('../components/common/ClearLabDialog', () => ({
  default: () => null,
}));
vi.mock('../components/auth/FirstUserDialog', () => ({
  default: () => null,
}));
vi.mock('../components/TimezoneSelect.jsx', () => ({
  default: () => React.createElement('select', null),
}));
vi.mock('../pages/settings/DiscoverySettingsPage.jsx', () => ({
  default: () => React.createElement('div', null, 'DiscoverySettings'),
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
vi.mock('../components/settings/NotificationsManager.jsx', () => ({
  default: () => React.createElement('div', null, 'NotificationsManager'),
}));
vi.mock('../components/settings/DbStatusPanel.jsx', () => ({
  default: () => React.createElement('div', null, 'DbStatusPanel'),
}));
vi.mock('../components/settings/HostStatsPanel.jsx', () => ({
  default: () => React.createElement('div', null, 'HostStatsPanel'),
}));

describe('SettingsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders settings page with navigation tabs', async () => {
    render(<SettingsPage />);

    await waitFor(() => {
      expect(screen.getByTestId('settings-nav')).toBeInTheDocument();
    });

    // Check settings nav has tabs rendered
    expect(screen.getByRole('button', { name: /^General$/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^Appearance$/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^Security$/ })).toBeInTheDocument();
  });

  it('displays the current tab label as heading', async () => {
    render(<SettingsPage />);

    await waitFor(() => {
      // Default active tab is 'general', so the heading should show General
      expect(screen.getByRole('heading', { name: /^General$/ })).toBeInTheDocument();
    });
  });

  it('renders Regional section with Language field on general tab', async () => {
    render(<SettingsPage />);

    await waitFor(() => {
      expect(screen.getByText('Regional')).toBeInTheDocument();
    });

    // Language field with dropdown
    expect(screen.getByText('Language')).toBeInTheDocument();
  });
});
