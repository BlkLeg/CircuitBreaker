import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { useSettings } from './SettingsContext.jsx';

const TIMEZONE_CACHE_KEY = 'cb-timezone';

const _browserTz = () => Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';

const _cachedTz = () => localStorage.getItem(TIMEZONE_CACHE_KEY) || _browserTz();

export const TimezoneContext = createContext({
  timezone: _cachedTz(),
  setTimezone: () => {},
});

export function TimezoneProvider({ children }) {
  const [timezone, _setTimezone] = useState(_cachedTz);
  const { settings, apiLoaded } = useSettings();

  // Sync from SettingsContext whenever settings.timezone changes.
  // Only apply after settings have actually loaded from the API to avoid
  // overwriting the localStorage cache with the DEFAULTS 'UTC' value.
  useEffect(() => {
    if (!apiLoaded) return;
    const tz = settings?.timezone;
    if (tz) {
      _setTimezone(tz);
      localStorage.setItem(TIMEZONE_CACHE_KEY, tz);
    }
  }, [settings?.timezone, apiLoaded]);

  // Allow local optimistic updates (e.g. from SettingsPage before the reload completes).
  const setTimezone = useCallback((tz) => {
    _setTimezone(tz);
    localStorage.setItem(TIMEZONE_CACHE_KEY, tz);
  }, []);

  return (
    <TimezoneContext.Provider value={{ timezone, setTimezone }}>
      {children}
    </TimezoneContext.Provider>
  );
}

export function useTimezone() {
  return useContext(TimezoneContext);
}
