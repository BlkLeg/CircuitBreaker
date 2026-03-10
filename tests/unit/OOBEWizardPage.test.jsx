import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import OOBEWizardPage from '../pages/OOBEWizardPage.jsx';

const mockBootstrapInitialize = vi.fn();
const mockUpdateProfile = vi.fn();
const mockLogin = vi.fn();
const mockSetAuthEnabled = vi.fn();
const mockReloadSettings = vi.fn();
const mockChangeLanguage = vi.fn().mockResolvedValue();

vi.mock('../api/auth.js', () => ({
  authApi: {
    bootstrapInitialize: (...args) => mockBootstrapInitialize(...args),
    updateProfile: (...args) => mockUpdateProfile(...args),
  },
}));

vi.mock('../context/AuthContext.jsx', () => ({
  useAuth: () => ({
    login: mockLogin,
    setAuthEnabled: mockSetAuthEnabled,
  }),
}));

vi.mock('../context/SettingsContext.jsx', () => ({
  useSettings: () => ({
    settings: {
      branding: null,
      ui_font: 'inter',
      ui_font_size: 'medium',
      language: 'en',
    },
    reloadSettings: mockReloadSettings,
  }),
}));

vi.mock('../components/TimezoneSelect.jsx', () => ({
  default: ({ value, onChange }) => (
    <select
      aria-label="Timezone"
      value={value}
      onChange={(event) => onChange(event.target.value)}
    >
      <option value="UTC">UTC</option>
    </select>
  ),
}));

vi.mock('../theme/applyTheme', () => ({
  applyTheme: vi.fn(),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    i18n: {
      changeLanguage: mockChangeLanguage,
    },
  }),
}));

describe('OOBEWizardPage', () => {
  beforeEach(() => {
    mockBootstrapInitialize.mockReset();
    mockUpdateProfile.mockReset();
    mockLogin.mockReset();
    mockSetAuthEnabled.mockReset();
    mockReloadSettings.mockReset();
    mockChangeLanguage.mockClear();
    mockBootstrapInitialize.mockResolvedValue({
      data: {
        token: 'bootstrap-token',
        user: {
          id: 1,
          email: 'admin@example.com',
          is_admin: true,
          is_superuser: true,
          display_name: 'Admin',
          language: 'en',
        },
        theme: { preset: 'one-dark' },
        vault_key_warning: false,
      },
    });
  });

  it('includes optional SMTP setup in the bootstrap payload', async () => {
    render(
      <MemoryRouter>
        <OOBEWizardPage />
      </MemoryRouter>
    );

    fireEvent.click(screen.getByRole('button', { name: 'Get Started' }));

    fireEvent.change(screen.getByLabelText('Email'), {
      target: { value: 'admin@example.com' },
    });
    fireEvent.change(screen.getByLabelText('Password'), {
      target: { value: 'Admin1234!' },
    });
    fireEvent.change(screen.getByLabelText('Confirm Password'), {
      target: { value: 'Admin1234!' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));

    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    fireEvent.click(screen.getByRole('button', { name: 'Continue →' }));

    fireEvent.change(screen.getByLabelText('External App URL (optional)'), {
      target: { value: 'https://cb.example.com' },
    });
    fireEvent.click(
      screen.getByLabelText(
        'Configure SMTP now for password reset emails and invite delivery.'
      )
    );
    fireEvent.change(screen.getByLabelText('SMTP Host'), {
      target: { value: 'smtp.example.com' },
    });
    fireEvent.change(screen.getByLabelText('From Email'), {
      target: { value: 'noreply@example.com' },
    });
    fireEvent.change(screen.getByLabelText('SMTP Password (optional)'), {
      target: { value: 'Mailer123!' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Continue →' }));

    fireEvent.click(
      screen.getByRole('button', { name: 'Create account and enter Circuit Breaker' })
    );

    await waitFor(() => {
      expect(mockBootstrapInitialize).toHaveBeenCalledWith(
        expect.objectContaining({
          email: 'admin@example.com',
          api_base_url: 'https://cb.example.com',
          smtp_enabled: true,
          smtp_host: 'smtp.example.com',
          smtp_from_email: 'noreply@example.com',
          smtp_password: 'Mailer123!',
        })
      );
    });
  });
});
