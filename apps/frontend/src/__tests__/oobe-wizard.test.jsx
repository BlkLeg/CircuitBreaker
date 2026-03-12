import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor, act } from '@testing-library/react';
import OOBEWizardPage from '../pages/OOBEWizardPage.jsx';

// Mock api client
vi.mock('../api/client', () => {
  const mockClient = {
    get: vi.fn().mockResolvedValue({ data: {} }),
    post: vi.fn().mockResolvedValue({ data: {} }),
    put: vi.fn(),
    patch: vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn(),
  };
  return {
    default: mockClient,
  };
});

vi.mock('../api/auth.js', () => ({
  OOBE_STEP_NAMES: ['welcome', 'account', 'theme', 'regional', 'network', 'finish'],
  authApi: {
    getOnboardingStep: vi.fn().mockResolvedValue({ data: { current_step: null } }),
    setOnboardingStep: vi.fn().mockResolvedValue({}),
    bootstrapInitialize: vi.fn().mockResolvedValue({ data: {} }),
    meWithToken: vi.fn().mockResolvedValue({ data: {} }),
  },
}));

vi.mock('react-router-dom', () => ({
  useNavigate: () => vi.fn(),
  useParams: () => ({}),
  useLocation: () => ({ pathname: '/oobe', search: '' }),
  Link: ({ children, ...props }) => React.createElement('a', props, children),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key, opts) => opts?.defaultValue || key,
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}));

vi.mock('../context/AuthContext.jsx', () => ({
  useAuth: () => ({
    user: null,
    login: vi.fn(),
  }),
}));

vi.mock('../context/SettingsContext.jsx', () => ({
  useSettings: () => ({
    settings: {
      ui_font: 'inter',
      ui_font_size: 'medium',
      language: 'en',
      api_base_url: '',
    },
    reloadSettings: vi.fn(),
  }),
}));

vi.mock('../theme/applyTheme', () => ({
  applyTheme: vi.fn(),
}));

vi.mock('../theme/presets', () => ({
  DEFAULT_PRESET: 'midnight',
  PRESET_LABELS: { midnight: 'Midnight', ocean: 'Ocean' },
  THEME_PRESETS: {
    midnight: { primary: '#6366f1' },
    ocean: { primary: '#0ea5e9' },
  },
}));

vi.mock('../lib/fonts', () => ({
  FONT_OPTIONS: [{ id: 'inter', label: 'Inter', stack: 'Inter, sans-serif', googleUrl: null }],
  FONT_SIZE_OPTIONS: [{ id: 'medium', label: 'Medium', rootPx: 14 }],
}));

vi.mock('../utils/md5.js', () => ({
  gravatarHash: vi.fn(() => 'abc123'),
}));

vi.mock('../utils/validation.js', () => ({
  sanitizeImageSrc: vi.fn((src) => src),
}));

vi.mock('../components/TimezoneSelect.jsx', () => ({
  default: () => React.createElement('select', { 'data-testid': 'timezone-select' }),
}));

vi.mock('../components/auth/OAuthProviderIcon.jsx', () => ({
  default: ({ name }) => React.createElement('span', null, name),
}));

vi.mock('lucide-react', () => ({
  Moon: () => React.createElement('span', null, 'Moon'),
  Sun: () => React.createElement('span', null, 'Sun'),
  Sparkles: () => React.createElement('span', null, 'Sparkles'),
  UserCircle2: () => React.createElement('span', null, 'UserCircle2'),
  X: () => React.createElement('span', null, 'X'),
  MapPin: () => React.createElement('span', null, 'MapPin'),
  Search: () => React.createElement('span', null, 'Search'),
  ShieldAlert: () => React.createElement('span', null, 'ShieldAlert'),
  Copy: () => React.createElement('span', null, 'Copy'),
  Download: () => React.createElement('span', null, 'Download'),
  CheckCircle2: () => React.createElement('span', null, 'CheckCircle2'),
  Lock: () => React.createElement('span', null, 'Lock'),
  ExternalLink: () => React.createElement('span', null, 'ExternalLink'),
}));

describe('OOBEWizardPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders first step (welcome) with Get Started button', async () => {
    render(<OOBEWizardPage onCompleted={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText(/create your first admin account/)).toBeInTheDocument();
    });

    expect(screen.getByText('Get Started')).toBeInTheDocument();
  });

  it('renders account creation step after clicking Get Started', async () => {
    render(<OOBEWizardPage onCompleted={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText('Get Started')).toBeInTheDocument();
    });

    await act(async () => {
      fireEvent.click(screen.getByText('Get Started'));
    });

    expect(screen.getByText('Create Account')).toBeInTheDocument();
    expect(screen.getByLabelText('Email')).toBeInTheDocument();
    expect(screen.getByLabelText('Password')).toBeInTheDocument();
    expect(screen.getByLabelText('Confirm Password')).toBeInTheDocument();
  });

  it('shows password validation rules on step 2', async () => {
    render(<OOBEWizardPage onCompleted={vi.fn()} />);

    // Move to step 2
    await waitFor(() => {
      expect(screen.getByText('Get Started')).toBeInTheDocument();
    });
    await act(async () => {
      fireEvent.click(screen.getByText('Get Started'));
    });

    // Check validation rules are visible
    expect(screen.getByText(/At least 8 characters/)).toBeInTheDocument();
    expect(screen.getByText(/One uppercase letter/)).toBeInTheDocument();
    expect(screen.getByText(/One lowercase letter/)).toBeInTheDocument();
    expect(screen.getByText(/One digit/)).toBeInTheDocument();
    expect(screen.getByText(/One special character/)).toBeInTheDocument();
  });

  it('prevents step progression when account fields are invalid', async () => {
    render(<OOBEWizardPage onCompleted={vi.fn()} />);

    // Move to step 2
    await waitFor(() => {
      expect(screen.getByText('Get Started')).toBeInTheDocument();
    });
    await act(async () => {
      fireEvent.click(screen.getByText('Get Started'));
    });

    // Try to proceed with empty fields by clicking Next
    const nextBtn = screen.getByText('Next');
    await act(async () => {
      fireEvent.click(nextBtn);
    });

    // Should show validation error and still be on step 2
    expect(screen.getByText(/Please fix account validation errors/)).toBeInTheDocument();
    expect(screen.getByText('Create Account')).toBeInTheDocument();
  });

  it('allows step progression when account fields are valid', async () => {
    render(<OOBEWizardPage onCompleted={vi.fn()} />);

    // Move to step 2
    await waitFor(() => {
      expect(screen.getByText('Get Started')).toBeInTheDocument();
    });
    await act(async () => {
      fireEvent.click(screen.getByText('Get Started'));
    });

    // Fill in valid account details
    await act(async () => {
      fireEvent.change(screen.getByLabelText('Email'), {
        target: { value: 'admin@example.com' },
      });
      fireEvent.change(screen.getByLabelText('Password'), {
        target: { value: 'StrongP@ss1' },
      });
      fireEvent.change(screen.getByLabelText('Confirm Password'), {
        target: { value: 'StrongP@ss1' },
      });
    });

    // Click Next - should advance to step 3 (theme)
    const nextBtn = screen.getByText('Next');
    await act(async () => {
      fireEvent.click(nextBtn);
    });

    // Step 3 shows theme chooser
    await waitFor(() => {
      expect(screen.getByText(/Choose your theme/)).toBeInTheDocument();
    });
  });
});
