import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { settingsApi } from '../api/client.jsx';

const _browserTz = () =>
  Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';

export const TimezoneContext = createContext({
  timezone: _browserTz(),
  setTimezone: () => {},
});

export function TimezoneProvider({ children }) {
  const [timezone, _setTimezone] = useState(_browserTz);

  // Load the persisted timezone from the settings API on mount.
  // Falls back to browser-detected timezone on network/API error.
  useEffect(() => {
    settingsApi
      .get()
      .then((res) => {
        const tz = res.data?.timezone;
        if (tz) {
          _setTimezone(tz);
        }
      })
      .catch(() => {
        // Non-critical — keep browser timezone on error
      });
  }, []);

  // Pure state setter — callers are responsible for persisting to the API.
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
