import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { useSettings } from './SettingsContext.jsx';

const _browserTz = () => Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';

export const TimezoneContext = createContext({
  timezone: _browserTz(),
  setTimezone: () => {},
});

export function TimezoneProvider({ children }) {
  const [timezone, _setTimezone] = useState(_browserTz);
  const { settings } = useSettings();

  // Sync from SettingsContext whenever settings.timezone changes.
  // This handles the initial load AND re-syncs after saves (reloadSettings()).
  // Falls back to browser-detected timezone until settings are loaded.
  useEffect(() => {
    const tz = settings?.timezone;
    if (tz) _setTimezone(tz);
  }, [settings?.timezone]);

  // Allow local optimistic updates (e.g. from SettingsPage before the reload completes).
  const setTimezone = useCallback((tz) => {
    _setTimezone(tz);
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
