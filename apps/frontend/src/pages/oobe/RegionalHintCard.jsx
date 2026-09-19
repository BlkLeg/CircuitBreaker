import React from 'react';
import { MapPin } from 'lucide-react';
/**
 * The aside beside step 5, explaining what the timezone and weather location are used for.
 *
 * Static markup with no wizard state of its own, so it takes neither props
 * nor the context — it was only ever inline because the page it belonged to
 * had nowhere else to put it.
 */
export default function RegionalHintCard() {
  return (
    <div className="oobe-hint-card">
      <div className="oobe-hint-header">
        <MapPin size={16} className="oobe-hint-icon" />
        <span>Location &amp; Weather</span>
      </div>
      <p className="oobe-hint-body">
        Search for your city to set up your <strong>weather widget</strong> and{' '}
        <strong>clock</strong> in one shot — the timezone is filled in automatically from the
        geocoding result.
      </p>
      <ul className="oobe-hint-combos">
        <li>
          <span className="oobe-hint-swatch" style={{ background: 'var(--color-primary)' }} />
          Type a city name and pick from the dropdown
        </li>
        <li>
          <span className="oobe-hint-swatch" style={{ background: 'var(--color-online)' }} />
          Timezone auto-updates to match your selection
        </li>
        <li>
          <span className="oobe-hint-swatch" style={{ background: 'var(--color-text-muted)' }} />
          Or manually choose a timezone below the search
        </li>
      </ul>
      <p className="oobe-hint-tip">
        💡 Weather data is powered by <strong>Open-Meteo</strong> — free, no API key required. You
        can change your location anytime in Settings → General.
      </p>
    </div>
  );
}
