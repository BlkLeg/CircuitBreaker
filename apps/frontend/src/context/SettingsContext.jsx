import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import PropTypes from 'prop-types';
import { settingsApi } from '../api/client';
import logger from '../utils/logger';
import { applyTheme } from '../theme/applyTheme';
import { THEME_PRESETS, DEFAULT_PRESET } from '../theme/presets';
import { useAppFont } from '../hooks/useAppFont';
import i18n from '../i18n';

// Pre-apply cached theme synchronously on module import to eliminate flash on reload.
// Runs before React renders; data-theme is not yet set so applyTheme runs in dark-mode
// mode (which is the correct default). The context effect will correct it after load.
const _cachedPreset = localStorage.getItem('cb-theme-preset');
if (_cachedPreset && _cachedPreset !== 'custom' && THEME_PRESETS[_cachedPreset]) {
  applyTheme(THEME_PRESETS[_cachedPreset], _cachedPreset);
}

const DEFAULTS = {
  id: 1,
  theme: 'dark',
  theme_preset: DEFAULT_PRESET,
  default_environment: '',
  show_experimental_features: false,
  api_base_url: '',
  map_default_filters: null,
  vendor_icon_mode: 'custom_files',
  environments: ['prod', 'staging', 'dev'],
  categories: [],
  locations: [],
  dock_order: null,
  show_header_widgets: true,
  show_time_widget: true,
  show_weather_widget: true,
  weather_location: 'Phoenix, AZ',
  timezone: 'UTC',
  language: 'en',
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
      const prefersDark = globalThis.matchMedia('(prefers-color-scheme: dark)').matches;
      root.dataset.theme = prefersDark ? 'dark' : 'light';
    } else {
      root.dataset.theme = theme;
    }
  }, [settings.theme]);

  // Apply theme colors (preset or custom) via CSS variables whenever theme settings change.
  // settings.theme is included so switching light/dark re-triggers applyTheme, allowing
  // it to removeProperty bg/surface overrides in light mode.
  useEffect(() => {
    let colors;
    const preset = settings.theme_preset;
    if (preset && preset !== 'custom' && THEME_PRESETS[preset]) {
      colors = THEME_PRESETS[preset];
    } else if (preset === 'custom' && settings.theme_colors) {
      colors = settings.theme_colors;
    } else if (settings.branding?.primary_color) {
      // Fallback: derive from branding for backwards compatibility
      const accents = settings.branding.accent_colors ?? [];
      colors = {
        primary: settings.branding.primary_color,
        secondary: '#0f172a',
        accent1: accents[0] ?? settings.branding.primary_color,
        accent2: accents[1] ?? settings.branding.primary_color,
        background: '#080c14',
        surface: '#0d1117',
      };
    } else {
      colors = THEME_PRESETS[DEFAULT_PRESET];
    }
    applyTheme(colors, preset ?? DEFAULT_PRESET);
  }, [settings.theme_preset, settings.theme_colors, settings.branding, settings.theme]);

  // Apply font family and font size preferences instantly via CSS variables.
  useAppFont(settings?.ui_font ?? 'inter', settings?.ui_font_size ?? 'medium');

  // Apply favicon, document title, and PWA manifest whenever branding changes
  useEffect(() => {
    const b = settings.branding;
    if (!b) return;
    if (b.favicon_path) {
      let link = document.querySelector("link[rel='icon']");
      if (!link) {
        link = document.createElement('link');
        link.rel = 'icon';
        document.head.appendChild(link);
      }
      link.href = `/favicon.ico?t=${Date.now()}`;
    }
    if (b.app_name) {
      document.title = b.app_name;
    }
    // Update PWA manifest to reflect current branding
    let manifest = document.querySelector("link[rel='manifest']");
    if (manifest) {
      manifest.href = `/api/v1/branding/manifest.json?t=${Date.now()}`;
    }
  }, [settings.branding]);

  useEffect(() => {
    const lang = settings.language || 'en';
    if (i18n.language !== lang) {
      i18n.changeLanguage(lang);
    }
  }, [settings.language]);

  const contextValue = useMemo(
    () => ({ settings, reloadSettings, loading }),
    [settings, reloadSettings, loading]
  );

  return <SettingsContext.Provider value={contextValue}>{children}</SettingsContext.Provider>;
}

SettingsProvider.propTypes = {
  children: PropTypes.node.isRequired,
};

export function useSettings() {
  return useContext(SettingsContext);
}
