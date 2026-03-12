import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import HardwarePage from '../pages/HardwarePage.jsx';

// Mock api client with named exports
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
    hardwareApi: {
      list: vi.fn(),
      get: vi.fn(),
      create: vi.fn(),
      update: vi.fn(),
      delete: vi.fn(),
    },
    clustersApi: {
      list: vi.fn().mockResolvedValue({ data: [] }),
      create: vi.fn(),
      update: vi.fn(),
      delete: vi.fn(),
    },
    computeUnitsApi: {
      list: vi.fn().mockResolvedValue({ data: [] }),
      uploadIcon: vi.fn(),
    },
    tagsApi: {
      list: vi.fn().mockResolvedValue({ data: [] }),
      update: vi.fn(),
    },
  };
});

// Must import AFTER mock
import { hardwareApi, tagsApi } from '../api/client';

vi.mock('../context/SettingsContext', () => ({
  useSettings: () => ({
    settings: {
      vendor_icon_mode: 'custom_files',
      locations: ['Rack A', 'Rack B'],
      environments: ['prod', 'dev'],
      show_page_hints: true,
    },
    reloadSettings: vi.fn(),
  }),
}));

const mockToast = {
  success: vi.fn(),
  error: vi.fn(),
  warn: vi.fn(),
  info: vi.fn(),
};
vi.mock('../components/common/Toast', () => ({
  useToast: () => mockToast,
}));

vi.mock('../utils/apiCache', () => ({
  createApiCache: (fn) => {
    const cached = (...args) => fn(...args);
    cached.invalidate = vi.fn();
    return cached;
  },
}));

// Mock heavy sub-components
vi.mock('../components/EntityTable', () => ({
  default: ({ columns, data, onRowClick }) =>
    React.createElement(
      'table',
      { 'data-testid': 'entity-table' },
      React.createElement(
        'thead',
        null,
        React.createElement(
          'tr',
          null,
          columns.map((col) => React.createElement('th', { key: col.key }, col.label))
        )
      ),
      React.createElement(
        'tbody',
        null,
        data.map((row) =>
          React.createElement(
            'tr',
            { key: row.id, onClick: () => onRowClick?.(row) },
            columns.map((col) =>
              React.createElement(
                'td',
                { key: col.key },
                typeof col.render === 'function'
                  ? col.render(row[col.key], row)
                  : String(row[col.key] ?? '')
              )
            )
          )
        )
      )
    ),
}));

vi.mock('../components/SearchBox', () => ({
  default: ({ value, onChange }) =>
    React.createElement('input', {
      'data-testid': 'search-box',
      value,
      onChange: (e) => onChange(e.target.value),
      placeholder: 'Search...',
    }),
}));

vi.mock('../components/TagFilter', () => ({
  default: () => React.createElement('div', { 'data-testid': 'tag-filter' }),
}));

vi.mock('../components/TagsCell', () => ({
  default: () => React.createElement('span', null, 'tags'),
}));

vi.mock('../components/details/HardwareDetail', () => ({
  default: () => null,
}));

vi.mock('../components/details/ClusterDetail', () => ({
  default: () => null,
}));

vi.mock('../components/common/FormModal', () => ({
  default: () => null,
}));

vi.mock('../components/common/ConfirmDialog', () => ({
  default: () => null,
}));

vi.mock('../components/common/IconPickerModal', () => ({
  default: () => null,
  IconImg: () => null,
}));

vi.mock('../components/common/SkeletonTable', () => ({
  SkeletonTable: () =>
    React.createElement('div', { 'data-testid': 'skeleton-table' }, 'Loading...'),
}));

vi.mock('../config/vendors', () => ({
  VENDORS: [
    { value: 'dell', label: 'Dell' },
    { value: 'hp', label: 'HP' },
  ],
}));

vi.mock('../config/hardwareRoles', () => ({
  HARDWARE_ROLES: [
    { value: 'compute', label: 'Compute' },
    { value: 'switch', label: 'Switch' },
    { value: 'router', label: 'Router' },
  ],
  HARDWARE_ROLE_LABELS: {
    compute: 'Compute',
    switch: 'Switch',
    router: 'Router',
  },
}));

vi.mock('../config/cpuBrands', () => ({
  CPU_BRANDS: [],
  CPU_BRAND_MAP: {},
}));

vi.mock('../icons/vendorIcons', () => ({
  getVendorIcon: () => ({ path: '/icons/default.png', label: 'Unknown' }),
}));

vi.mock('../utils/validation', () => ({
  validateIpAddress: vi.fn(() => null),
  validateDuplicateName: vi.fn(() => null),
}));

describe('HardwarePage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders hardware table with items', async () => {
    hardwareApi.list.mockResolvedValue({
      data: [
        {
          id: 1,
          name: 'Server-01',
          role: 'compute',
          ip_address: '10.0.0.1',
          vendor: 'dell',
          model: 'R740',
          cpu: 'Xeon',
          memory_gb: 128,
          location: 'Rack A',
        },
        {
          id: 2,
          name: 'Switch-01',
          role: 'switch',
          ip_address: '10.0.0.2',
          vendor: 'hp',
          model: '2930F',
          cpu: null,
          memory_gb: null,
          location: 'Rack B',
        },
      ],
    });
    tagsApi.list.mockResolvedValue({ data: [] });

    render(<HardwarePage />);

    await waitFor(() => {
      expect(screen.getByTestId('entity-table')).toBeInTheDocument();
    });

    expect(screen.getByText('Server-01')).toBeInTheDocument();
    expect(screen.getByText('Switch-01')).toBeInTheDocument();
  });

  it('renders empty state when no hardware', async () => {
    hardwareApi.list.mockResolvedValue({ data: [] });
    tagsApi.list.mockResolvedValue({ data: [] });

    render(<HardwarePage />);

    await waitFor(() => {
      expect(screen.queryByTestId('skeleton-table')).not.toBeInTheDocument();
    });

    // With show_page_hints enabled and no items, the tip should show
    expect(screen.getByText(/Start by adding hardware nodes/)).toBeInTheDocument();
  });

  it('shows loading skeleton initially', async () => {
    // Make the API call hang so loading state is visible
    hardwareApi.list.mockReturnValue(new Promise(() => {}));
    tagsApi.list.mockResolvedValue({ data: [] });

    render(<HardwarePage />);

    expect(screen.getByTestId('skeleton-table')).toBeInTheDocument();
  });

  it('renders the Add Hardware button', async () => {
    hardwareApi.list.mockResolvedValue({ data: [] });
    tagsApi.list.mockResolvedValue({ data: [] });

    render(<HardwarePage />);

    expect(screen.getByText('+ Add Hardware')).toBeInTheDocument();
  });
});
