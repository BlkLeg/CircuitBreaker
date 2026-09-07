import React from 'react';
import { ShieldAlert } from 'lucide-react';
import { FONT_OPTIONS, FONT_SIZE_OPTIONS } from '../../lib/fonts';
import { PRESET_LABELS } from '../../theme/presets';
import { sanitizeImageSrc } from '../../utils/validation.js';
import { timezoneToCity } from './constants';
import { useOOBE } from './OOBEContext';

/**
 * Step 7 — the review panel and the call that actually creates everything.
 *
 * Reads the wizard context rather than taking props; see `OOBEContext`
 * for why.
 */
export default function ReviewStep() {
  const {
    avatarLoadError,
    displayName,
    email,
    externalAppUrl,
    goBack,
    gravatarPreview,
    photoPreview,
    selectedFont,
    selectedFontSize,
    selectedPreset,
    selectedThemeMode,
    setAvatarLoadError,
    smtpEnabled,
    smtpFromEmail,
    smtpHost,
    submitBootstrap,
    submitting,
    timezone,
    weatherLocation,
  } = useOOBE();

  return (
    <>
      <h2 className="login-card-title">Confirmation</h2>
      <p className="login-card-subtitle">Review and complete setup.</p>

      <div className="oobe-summary">
        {avatarLoadError ? (
          <div className="oobe-avatar oobe-avatar-fallback" aria-hidden="true">
            {(displayName || email)[0]?.toUpperCase() || '?'}
          </div>
        ) : (
          <img
            src={sanitizeImageSrc(photoPreview || gravatarPreview)}
            alt="Avatar preview"
            className="oobe-avatar"
            onError={() => setAvatarLoadError(true)}
          />
        )}
        <div className="oobe-summary-details">
          <div className="oobe-summary-email">{email}</div>
          <div>
            <strong>Display Name:</strong> {displayName || '(auto from email)'}
          </div>
          <div>
            <strong>Theme:</strong> {PRESET_LABELS[selectedPreset] ?? selectedPreset} (
            {selectedThemeMode})
          </div>
          <div>
            <strong>Font:</strong>{' '}
            {FONT_OPTIONS.find((entry) => entry.id === selectedFont)?.label ?? selectedFont} ·{' '}
            {FONT_SIZE_OPTIONS.find((entry) => entry.id === selectedFontSize)?.label ??
              selectedFontSize}
          </div>
          <div>
            <strong>Timezone:</strong> {timezone}
          </div>
          {(weatherLocation || timezoneToCity(timezone)) && (
            <div>
              <strong>Weather:</strong> {weatherLocation || timezoneToCity(timezone)}
            </div>
          )}
          <div>
            <strong>External App URL:</strong> {externalAppUrl.trim() || 'Not set yet'}
          </div>
          <div>
            <strong>Email Recovery:</strong>{' '}
            {smtpEnabled
              ? `${smtpHost || 'SMTP'} via ${smtpFromEmail || 'configured sender'}`
              : 'Skipped for now'}
          </div>
        </div>
      </div>

      <div className="oobe-beta-warning" role="note" aria-label="Beta security advisory">
        <div className="oobe-beta-warning-tape oobe-beta-warning-tape--top" />
        <div className="oobe-beta-warning-tape oobe-beta-warning-tape--bottom" />
        <div className="oobe-beta-warning-header">
          <ShieldAlert size={16} />
          <strong>Beta Advisory</strong>
        </div>
        <p>
          Circuit Breaker is in beta. Run it with good security habits: keep your vault key backed
          up, use strong unique passwords, restrict network exposure, and keep updates current.
        </p>
      </div>

      <div className="oobe-actions">
        <button type="button" className="btn btn-secondary" onClick={goBack} disabled={submitting}>
          Back
        </button>
        <button
          type="button"
          className="btn btn-primary"
          onClick={submitBootstrap}
          disabled={submitting}
        >
          {submitting ? 'Creating…' : 'Create account and enter Circuit Breaker'}
        </button>
      </div>
    </>
  );
}
