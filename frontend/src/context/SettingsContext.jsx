import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import PropTypes from 'prop-types';
import { settingsApi } from '../api/client';
import logger from '../utils/logger';

const DEFAULTS = {
  id: 1,
  theme: 'dark',
  default_environment: '',
  show_experimental_features: false,
  api_base_url: '',
  map_default_filters: null,
  vendor_icon_mode: 'custom_files',
  environments: ['prod', 'staging', 'dev'],
  categories: [],
  locations: [],
  dock_order: null,
};

const SettingsContext = createContext({
  settings: DEFAULTS,
  reloadSettings: async () => {},
  loading: true,
});

export function SettingsProvider({ children }) {
  const [settings, setSettings] = useState(DEFAULTS);
  const [loading, setLoading] = useState(true);

  const reloadSettings = useCallback(async () => {
    try {
      const res = await settingsApi.get();
      setSettings(res.data);
    } catch (err) {
      logger.error('Failed to load settings:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    reloadSettings();
  }, [reloadSettings]);

  // Apply theme to <html data-theme="..."> whenever it changes
  useEffect(() => {
    const root = document.documentElement;
    const theme = settings.theme ?? 'dark';
    if (theme === 'auto') {
      const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
      root.setAttribute('data-theme', prefersDark ? 'dark' : 'light');
    } else {
      root.setAttribute('data-theme', theme);
    }
  }, [settings.theme]);


  const contextValue = useMemo(
    () => ({ settings, reloadSettings, loading }),
    [settings, reloadSettings, loading],
  );

  return (
    <SettingsContext.Provider value={contextValue}>
      {children}
    </SettingsContext.Provider>
  );
}

SettingsProvider.propTypes = {
  children: PropTypes.node.isRequired,
};

export function useSettings() {
  return useContext(SettingsContext);
}
