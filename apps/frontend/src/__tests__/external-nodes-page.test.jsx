import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import ExternalNodesPage from '../pages/ExternalNodesPage.jsx';

vi.mock('../api/client', () => ({
  externalNodesApi: {
    list: vi.fn().mockResolvedValue({ data: [] }),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    getNetworks: vi.fn().mockResolvedValue({ data: [] }),
    getServices: vi.fn().mockResolvedValue({ data: [] }),
    addNetwork: vi.fn(),
    removeNetwork: vi.fn(),
  },
  networksApi: {
    list: vi.fn().mockResolvedValue({ data: [] }),
  },
  tagsApi: {
    list: vi.fn().mockResolvedValue({ data: [] }),
    update: vi.fn(),
  },
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

vi.mock('../context/SettingsContext', () => ({
  useSettings: () => ({
    settings: {
      environments: ['prod', 'dev'],
      show_page_hints: false,
    },
  }),
}));

vi.mock('../components/EntityTable', () => ({
  default: () => <div data-testid="entity-table" />,
}));

vi.mock('../components/SearchBox', () => ({
  default: () => <div data-testid="search-box" />,
}));

vi.mock('../components/TagFilter', () => ({
  default: () => <div data-testid="tag-filter" />,
}));

vi.mock('../components/TagsCell', () => ({
  default: () => <div data-testid="tags-cell" />,
}));

vi.mock('../components/common/Drawer', () => ({
  default: () => null,
}));

vi.mock('../components/common/ConfirmDialog', () => ({
  default: () => null,
}));

vi.mock('../components/common/SkeletonTable', () => ({
  SkeletonTable: () => <div data-testid="skeleton-table" />,
}));

vi.mock('../utils/validation', () => ({
  validateDuplicateName: vi.fn(() => null),
}));

vi.mock('../components/common/FormModal', () => ({
  default: ({ open, fields }) => {
    if (!open) return null;
    const iconField = fields.find((f) => f.name === 'icon_slug');
    return (
      <div data-testid="external-form-modal">
        <button
          type="button"
          onClick={() => iconField?.onOpenPicker?.(iconField.value ?? null, vi.fn())}
        >
          Choose icon
        </button>
      </div>
    );
  },
}));

vi.mock('../components/common/IconPickerModal', () => ({
  __esModule: true,
  default: () => <div data-testid="icon-picker-modal" />,
  IconImg: () => null,
}));

describe('ExternalNodesPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('opens icon picker from external node form', async () => {
    render(<ExternalNodesPage />);
    await waitFor(() => expect(screen.queryByTestId('skeleton-table')).not.toBeInTheDocument());

    fireEvent.click(screen.getByText('+ Add External Node'));
    expect(screen.getByTestId('external-form-modal')).toBeInTheDocument();

    fireEvent.click(screen.getByText('Choose icon'));
    expect(screen.getByTestId('icon-picker-modal')).toBeInTheDocument();
  });
});
