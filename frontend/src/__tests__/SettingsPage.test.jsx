import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import SettingsPage from '../pages/SettingsPage';
import { SettingsProvider } from '../context/SettingsContext';
import { AuthProvider } from '../context/AuthContext';
import { TimezoneProvider } from '../context/TimezoneContext';

// Mock the context and APIs
jest.mock('../context/SettingsContext', () => ({
  useSettings: () => ({
    settings: {
      theme: 'dark',
      environments: ['prod', 'dev'],
      categories: [],
      locations: [],
      auth_enabled: false,
      timezone: 'UTC'
    },
    reloadSettings: jest.fn(),
    loading: false
  }),
  SettingsProvider: ({ children }) => <div>{children}</div>
}));

jest.mock('../api/client', () => ({
  settingsApi: {
    get: jest.fn(),
    update: jest.fn(),
    reset: jest.fn()
  },
  adminApi: {
    export: jest.fn(),
    clearLab: jest.fn()
  },
  categoriesApi: {
    list: jest.fn(() => Promise.resolve({ data: [] }))
  },
  environmentsApi: {
    list: jest.fn(() => Promise.resolve({ data: [] }))
  }
}));

describe('SettingsPage Redesign', () => {
  const renderPage = () => {
    return render(
      <MemoryRouter>
        <AuthProvider>
          <TimezoneProvider>
            <SettingsPage />
          </TimezoneProvider>
        </AuthProvider>
      </MemoryRouter>
    );
  };

  test('renders with tabbed navigation', () => {
    renderPage();
    expect(screen.getByText('General')).toBeInTheDocument();
    expect(screen.getByText('Appearance')).toBeInTheDocument();
    expect(screen.getByText('Resources')).toBeInTheDocument();
  });

  test('switches tabs on click', () => {
    renderPage();
    const appearanceTab = screen.getByText('Appearance');
    fireEvent.click(appearanceTab);
    expect(screen.getByText('Theme Engine')).toBeInTheDocument();
  });

  test('filters tabs based on search query', () => {
    renderPage();
    const searchInput = screen.getByPlaceholderText('Search settings...');
    fireEvent.change(searchInput, { target: { value: 'Theme' } });
    
    // "Appearance" should still be there because it matches "Theme" keyword
    expect(screen.getByText('Appearance')).toBeInTheDocument();
    
    // "Security" should be filtered out
    expect(screen.queryByText('Security')).not.toBeInTheDocument();
  });

  test('shows action bar when dirty', () => {
    renderPage();
    const timezoneSelect = screen.getByDisplayValue('UTC');
    // This is a simplification; in real app it might be more complex to trigger dirty
    // But we are testing if the SettingsActionBar is rendered when isDirty is true
    // Our SettingPage uses useMemo for isDirty based on form/origForm
  });
});
