import React from 'react';
import { MapPin, Search, X } from 'lucide-react';
import TimezoneSelect from '../../components/TimezoneSelect.jsx';
import { useOOBE } from './OOBEContext';

/**
 * Step 5 — timezone and the weather location the header widget uses.
 *
 * Reads the wizard context rather than taking props; see `OOBEContext`
 * for why.
 */
export default function RegionalStep() {
  const {
    goBack,
    goNext,
    handleLocationQueryChange,
    handleTimezoneChange,
    locationDropdownOpen,
    locationDropdownRef,
    locationInputRef,
    locationQuery,
    locationResults,
    locationSearching,
    selectLocationResult,
    setLocationDropdownOpen,
    setLocationQuery,
    setLocationResults,
    timezone,
    weatherLocation,
  } = useOOBE();

  return (
    <>
      <h2 className="login-card-title">Regional Preferences</h2>
      <p className="login-card-subtitle">
        Your location powers the live weather and clock widgets in the header.
      </p>

      {/* Location search — ties weather + timezone together */}
      <div className="oobe-location-field">
        <label className="login-label" htmlFor="oobe-location-search">
          Your Location
        </label>
        <div className="oobe-location-input-wrap" ref={locationDropdownRef}>
          <span className="oobe-location-icon" aria-hidden="true">
            {locationSearching ? (
              <Search size={13} className="oobe-location-spin" />
            ) : (
              <MapPin size={13} />
            )}
          </span>
          <input
            id="oobe-location-search"
            ref={locationInputRef}
            type="text"
            className="login-input oobe-location-input"
            placeholder={weatherLocation || 'Search for your city…'}
            value={locationQuery}
            onChange={handleLocationQueryChange}
            onFocus={() => locationResults.length > 0 && setLocationDropdownOpen(true)}
            autoComplete="off"
          />
          {locationQuery && (
            <button
              type="button"
              className="oobe-location-clear"
              onClick={() => {
                setLocationQuery('');
                setLocationResults([]);
                setLocationDropdownOpen(false);
              }}
              aria-label="Clear location search"
            >
              <X size={12} />
            </button>
          )}
          {locationDropdownOpen && locationResults.length > 0 && (
            <ul className="oobe-location-dropdown">
              {locationResults.map((result) => (
                <li key={result.id}>
                  <button
                    type="button"
                    className="oobe-location-result"
                    onClick={() => selectLocationResult(result)}
                  >
                    <MapPin size={11} className="oobe-location-result-icon" />
                    <span className="oobe-location-result-name">{result.name}</span>
                    {(result.admin1 || result.country) && (
                      <span className="oobe-location-result-meta">
                        {[result.admin1, result.country].filter(Boolean).join(', ')}
                      </span>
                    )}
                    {result.timezone && (
                      <span className="oobe-location-result-tz">{result.timezone}</span>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        {weatherLocation && !locationQuery && (
          <p className="oobe-location-active">
            <MapPin size={10} /> Using <strong>{weatherLocation}</strong>
            {timezone !== 'UTC' && (
              <>
                {' '}
                · Timezone set to <strong>{timezone}</strong>
              </>
            )}
          </p>
        )}
      </div>

      <div style={{ margin: '0 0 8px' }}>
        <TimezoneSelect value={timezone} onChange={handleTimezoneChange} />
      </div>

      <p
        style={{
          fontSize: '0.7rem',
          color: 'var(--color-text-muted)',
          margin: '4px 0 0',
        }}
      >
        All of these can be changed anytime in Settings → General.
      </p>
      <div className="oobe-actions">
        <button type="button" className="btn btn-secondary" onClick={goBack}>
          Back
        </button>
        <button type="button" className="btn btn-primary" onClick={goNext}>
          Continue →
        </button>
      </div>
    </>
  );
}
