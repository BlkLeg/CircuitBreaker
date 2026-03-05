import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { useNavigate } from 'react-router-dom';
import { Moon, Sun, Sparkles, UserCircle2, X, MapPin, Search } from 'lucide-react';
import { authApi } from '../api/auth.js';
import { useAuth } from '../context/AuthContext.jsx';
import { useSettings } from '../context/SettingsContext.jsx';
import { applyTheme } from '../theme/applyTheme';
import { DEFAULT_PRESET, PRESET_LABELS, THEME_PRESETS } from '../theme/presets';
import { FONT_OPTIONS, FONT_SIZE_OPTIONS } from '../lib/fonts';
import { gravatarHash } from '../utils/md5.js';
import { sanitizeImageSrc } from '../utils/validation.js';
import TimezoneSelect from '../components/TimezoneSelect.jsx';
import { useTranslation } from 'react-i18next';

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

const RULES = [
  { label: 'At least 8 characters', test: (p) => p.length >= 8 },
  { label: 'One uppercase letter', test: (p) => /[A-Z]/.test(p) },
  { label: 'One lowercase letter', test: (p) => /[a-z]/.test(p) },
  { label: 'One digit', test: (p) => /\d/.test(p) },
  { label: 'One special character', test: (p) => /[^A-Za-z0-9]/.test(p) },
];

const PRESET_KEYS = Object.keys(THEME_PRESETS);

/** Derive a human-readable city name from an IANA timezone string. */
function timezoneToCity(tz) {
  if (!tz || tz === 'UTC' || tz === 'GMT') return '';
  const parts = tz.split('/');
  return parts[parts.length - 1].replaceAll('_', ' ');
}

function OOBEWizardPage({ onCompleted }) {
  const { i18n } = useTranslation();
  const navigate = useNavigate();
  const { login, setAuthEnabled } = useAuth();
  const { settings, reloadSettings } = useSettings();
  const branding = settings?.branding;

  const [step, setStep] = useState(1);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [selectedPreset, setSelectedPreset] = useState(DEFAULT_PRESET);
  const [selectedThemeMode, setSelectedThemeMode] = useState('dark');
  const [selectedFont, setSelectedFont] = useState(settings?.ui_font ?? 'inter');
  const [selectedFontSize, setSelectedFontSize] = useState(settings?.ui_font_size ?? 'medium');
  const [language, setLanguage] = useState(settings?.language ?? 'en');
  const [timezone, setTimezone] = useState(
    () => Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  );
  const [weatherLocation, setWeatherLocation] = useState(
    () => timezoneToCity(Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC')
  );
  const [locationQuery, setLocationQuery] = useState('');
  const [locationResults, setLocationResults] = useState([]);
  const [locationSearching, setLocationSearching] = useState(false);
  const [locationDropdownOpen, setLocationDropdownOpen] = useState(false);
  const locationDebounceRef = useRef(null);
  const locationInputRef = useRef(null);
  const locationDropdownRef = useRef(null);
  const [photoFile, setPhotoFile] = useState(null);
  const [photoPreview, setPhotoPreview] = useState(null);
  const photoFileRef = useRef(null);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const languages = [
    { value: 'en', label: 'English' },
    { value: 'es', label: 'Español' },
    { value: 'fr', label: 'Français' },
    { value: 'de', label: 'Deutsch' },
    { value: 'zh', label: '中文 (简体)' },
    { value: 'ja', label: '日本語' },
  ];

  const handlePhotoFile = (e) => {
    const f = e.target.files[0];
    if (!f) return;
    if (f.size > 10 * 1024 * 1024) { setError('Photo must be ≤ 10 MB.'); return; }
    if (!['image/jpeg', 'image/png'].includes(f.type)) { setError('Photo must be JPEG or PNG.'); return; }
    setError('');
    setPhotoFile(f);
    setPhotoPreview(URL.createObjectURL(f));
  };

  const clearPhoto = () => {
    setPhotoFile(null);
    setPhotoPreview(null);
    if (photoFileRef.current) photoFileRef.current.value = '';
  };

  useEffect(() => {
    const handler = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        setLocationDropdownOpen(false);
      }
    };
    globalThis.addEventListener('keydown', handler, true);
    return () => globalThis.removeEventListener('keydown', handler, true);
  }, []);

  // Close location dropdown when clicking outside
  useEffect(() => {
    const handler = (e) => {
      if (
        locationDropdownRef.current &&
        !locationDropdownRef.current.contains(e.target) &&
        locationInputRef.current &&
        !locationInputRef.current.contains(e.target)
      ) {
        setLocationDropdownOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const searchLocation = useCallback(async (query) => {
    const q = query.trim();
    if (q.length < 2) {
      setLocationResults([]);
      setLocationDropdownOpen(false);
      return;
    }
    setLocationSearching(true);
    try {
      const res = await fetch(
        `https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(q)}&count=6&language=en&format=json`
      );
      const data = await res.json();
      const results = (data.results || []).map((r) => ({
        id: r.id,
        name: r.name,
        admin1: r.admin1,
        country: r.country,
        timezone: r.timezone,
        display: [r.name, r.admin1, r.country].filter(Boolean).join(', '),
      }));
      setLocationResults(results);
      setLocationDropdownOpen(results.length > 0);
    } catch {
      setLocationResults([]);
    } finally {
      setLocationSearching(false);
    }
  }, []);

  const handleLocationQueryChange = (e) => {
    const val = e.target.value;
    setLocationQuery(val);
    clearTimeout(locationDebounceRef.current);
    locationDebounceRef.current = setTimeout(() => searchLocation(val), 320);
  };

  const selectLocationResult = (result) => {
    setWeatherLocation(result.name);
    setLocationQuery(result.display);
    if (result.timezone) {
      setTimezone(result.timezone);
    }
    setLocationResults([]);
    setLocationDropdownOpen(false);
  };

  const handleTimezoneChange = (tz) => {
    setTimezone(tz);
    // Only auto-fill location if user hasn't manually picked one via search
    const derived = timezoneToCity(tz);
    if (derived) {
      setWeatherLocation(derived);
      setLocationQuery('');
    }
  };

  const emailValid = EMAIL_RE.test(email);
  const rulesPassed = useMemo(() => RULES.every((rule) => rule.test(password)), [password]);
  const passwordsMatch = password.length > 0 && password === confirmPassword;
  const gravatarPreview = emailValid
    ? `https://www.gravatar.com/avatar/${gravatarHash(email)}?s=384&d=mp`
    : 'https://www.gravatar.com/avatar/?s=384&d=mp';

  const accountValid = emailValid && rulesPassed && passwordsMatch;

  const goNext = () => {
    if (step === 2 && !accountValid) {
      setError('Please fix account validation errors before continuing.');
      return;
    }
    setError('');
    setStep((value) => Math.min(5, value + 1));
  };

  const goBack = () => {
    setError('');
    setStep((value) => Math.max(1, value - 1));
  };

  const applyFontInstant = (fontId, fontSizeId) => {
    const font = FONT_OPTIONS.find((entry) => entry.id === fontId) ?? FONT_OPTIONS.find((entry) => entry.id === 'inter') ?? FONT_OPTIONS[0];
    const size = FONT_SIZE_OPTIONS.find((entry) => entry.id === fontSizeId) ?? FONT_SIZE_OPTIONS.find((entry) => entry.id === 'medium') ?? FONT_SIZE_OPTIONS[0];

    const existingLink = document.getElementById('cb-font-link');
    if (font.googleUrl) {
      const link = existingLink ?? document.createElement('link');
      link.id = 'cb-font-link';
      link.rel = 'stylesheet';
      link.href = font.googleUrl;
      if (!existingLink) document.head.appendChild(link);
      else link.href = font.googleUrl;
    } else {
      existingLink?.remove();
    }

    document.documentElement.style.setProperty('--font', font.stack);
    document.documentElement.style.setProperty('--font-size-base', `${size.rootPx}px`);
    document.documentElement.style.fontSize = `${size.rootPx}px`;
  };

  const submitBootstrap = async () => {
    if (!accountValid) {
      setStep(2);
      setError('Account details are invalid.');
      return;
    }
    setSubmitting(true);
    setError('');
    try {
      const response = await authApi.bootstrapInitialize({
        email,
        password,
        display_name: displayName || undefined,
        theme_preset: selectedPreset,
        theme: selectedThemeMode,
        timezone,
        language,
        ui_font: selectedFont,
        ui_font_size: selectedFontSize,
        weather_location: weatherLocation || timezoneToCity(timezone) || undefined,
      });

      const token = response.data.token;
      let user = response.data.user;
      const preset = response.data.theme?.preset || selectedPreset;

      if (photoFile) {
        try {
          const fd = new FormData();
          fd.append('profile_photo', photoFile);
          const photoRes = await authApi.updateProfile(fd, token);
          user = photoRes.data;
        } catch {
          // Photo upload failed — account was still created successfully
        }
      }

      if (THEME_PRESETS[preset]) {
        applyTheme(THEME_PRESETS[preset], preset);
      }
      await i18n.changeLanguage(language);

      login(token, user);
      setAuthEnabled(true);
      await reloadSettings();
      onCompleted?.();
      navigate('/map', { replace: true });
    } catch (err) {
      if (err.statusCode === 409) {
        onCompleted?.();
        navigate('/login', {
          replace: true,
          state: { message: 'Bootstrap already completed. Please sign in.' },
        });
        return;
      }
      setError(err.message || 'Bootstrap failed. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  const applyModeInstant = (mode) => {
    document.documentElement.dataset.theme = mode;
    applyTheme(THEME_PRESETS[selectedPreset], selectedPreset);
  };

  const selectPreset = (key) => {
    setSelectedPreset(key);
    setError('');
    applyTheme(THEME_PRESETS[key], key);
  };

  const selectMode = (mode) => {
    setSelectedThemeMode(mode);
    applyModeInstant(mode);
  };

  const regionalHintCard = (
    <div className="oobe-hint-card">
      <div className="oobe-hint-header">
        <MapPin size={16} className="oobe-hint-icon" />
        <span>Location &amp; Weather</span>
      </div>
      <p className="oobe-hint-body">
        Search for your city to set up your <strong>weather widget</strong> and <strong>clock</strong> in one shot — the timezone is filled in automatically from the geocoding result.
      </p>
      <ul className="oobe-hint-combos">
        <li><span className="oobe-hint-swatch" style={{ background: 'var(--color-primary)' }} />Type a city name and pick from the dropdown</li>
        <li><span className="oobe-hint-swatch" style={{ background: 'var(--color-online)' }} />Timezone auto-updates to match your selection</li>
        <li><span className="oobe-hint-swatch" style={{ background: 'var(--color-text-muted)' }} />Or manually choose a timezone below the search</li>
      </ul>
      <p className="oobe-hint-tip">
        💡 Weather data is powered by <strong>Open-Meteo</strong> — free, no API key required. You can change your location anytime in Settings → General.
      </p>
    </div>
  );

  const avatarHintCard = (
    <div className="oobe-hint-card">
      <div className="oobe-hint-header">
        <UserCircle2 size={16} className="oobe-hint-icon" />
        <span>Profile Photo</span>
      </div>
      <p className="oobe-hint-body">
        Your avatar is pulled automatically from <strong>Gravatar</strong> using your email address — no upload needed.
      </p>
      <ul className="oobe-hint-combos">
        <li><span className="oobe-hint-swatch" style={{ background: 'var(--color-primary)' }} />Type your email and the preview updates live</li>
        <li><span className="oobe-hint-swatch" style={{ background: 'var(--color-text-muted)' }} />No Gravatar? Click the photo to upload your own JPEG or PNG</li>
        <li><span className="oobe-hint-swatch" style={{ background: 'var(--color-online)' }} />Custom upload always takes priority over Gravatar</li>
      </ul>
      <p className="oobe-hint-tip">
        💡 You can update your photo any time from your profile in the header. Max size: 10 MB.
      </p>
    </div>
  );

  const themeHintCard = (
    <div className="oobe-hint-card">
      <div className="oobe-hint-header">
        <Sparkles size={16} className="oobe-hint-icon" />
        <span>Mix &amp; Match</span>
      </div>
      <p className="oobe-hint-body">
        Every theme has both a <strong>dark</strong> and <strong>light</strong> variant.
        Use the toggle above to flip modes as you try presets — your perfect combination is out there.
      </p>
      <ul className="oobe-hint-combos">
        <li><span className="oobe-hint-swatch" style={{ background: '#00f5ff' }} />Cyberpunk Neon + Dark — high-contrast night</li>
        <li><span className="oobe-hint-swatch" style={{ background: '#8be9fd' }} />Dracula + Light — soft pastel daytime</li>
        <li><span className="oobe-hint-swatch" style={{ background: '#a9dc76' }} />Monokai + Dark — warm retro terminal</li>
        <li><span className="oobe-hint-swatch" style={{ background: '#b48ead' }} />Nord + Light — calm Nordic workspace</li>
      </ul>
      <p className="oobe-hint-tip">
        💡 You can change your theme and mode any time from the header or <em>Settings → Appearance</em>.
      </p>
    </div>
  );

  return (
    <div className="login-root">
      <div className="login-bokeh-tl" aria-hidden="true" />
      <div className="login-bokeh-br" aria-hidden="true" />
      <div className={`oobe-layout${step === 2 || step === 3 || step === 4 ? ' oobe-layout--theme-step' : ''}`}>
        <div className="oobe-header">
          <img
            src={branding?.login_logo_path ?? '/CB-AZ_Final.png'}
            alt={branding?.app_name ?? 'Circuit Breaker'}
          />
          {/* Brand name removed - logo is sufficient */}
          <div className="login-status" style={{ marginTop: 4 }}>
            <span className="login-status-dot status-indicator--online" aria-hidden="true" />{' '}First-run setup
          </div>
        </div>

        {/* Mobile hint — shown above the card on relevant steps */}
        {step === 2 && (
          <div className="oobe-hint-mobile-wrap">{avatarHintCard}</div>
        )}
        {step === 3 && (
          <div className="oobe-hint-mobile-wrap">{themeHintCard}</div>
        )}
        {step === 4 && (
          <div className="oobe-hint-mobile-wrap">{regionalHintCard}</div>
        )}

        <div className={`oobe-step3-row${step === 2 || step === 3 || step === 4 ? ' oobe-step3-row--active' : ''}`}>
        <div className="login-card oobe-card">
          <div className="oobe-progress">Step {step}/5</div>

          {step === 1 && (
            <>
              {/* Card title removed - logo and context are sufficient */}
              <p className="login-card-subtitle">
                Let’s create your first admin account and personalize your dashboard.
              </p>
              <div className="oobe-actions">
                <button type="button" className="btn btn-primary login-btn-submit" onClick={goNext}>
                  Get Started
                </button>
              </div>
            </>
          )}

          {step === 2 && (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                goNext();
              }}
              noValidate
            >
              <h2 className="login-card-title">Create Account</h2>
              <p className="login-card-subtitle">Create the first admin account for this installation.</p>

              <div className="oobe-avatar-wrap">
                <button
                  type="button"
                  className="oobe-avatar-btn"
                  onClick={() => photoFileRef.current?.click()}
                  title="Upload profile photo (optional)"
                >
                  <img src={sanitizeImageSrc(photoPreview || gravatarPreview)} alt="Avatar preview" className="oobe-avatar" />
                  <span className="oobe-avatar-overlay" aria-hidden="true">📷</span>
                </button>
                {photoFile ? (
                  <div className="oobe-avatar-status">
                    <span className="oobe-avatar-status-text">✓ Custom photo ready</span>
                    <button type="button" className="oobe-avatar-clear" onClick={clearPhoto} title="Remove custom photo">
                      <X size={11} /> Remove
                    </button>
                  </div>
                ) : (
                  <span className="oobe-avatar-status-text oobe-avatar-status-text--muted">
                    Using Gravatar · click to upload your own
                  </span>
                )}
                <input
                  ref={photoFileRef}
                  type="file"
                  accept="image/jpeg,image/png"
                  style={{ display: 'none' }}
                  onChange={handlePhotoFile}
                />
              </div>

              <div className="login-field">
                <label className="login-label" htmlFor="oobe-email">Email</label>
                <input
                  id="oobe-email"
                  type="email"
                  className="login-input"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                />
              </div>

              <div className="login-field">
                <label className="login-label" htmlFor="oobe-display-name">Display Name (optional)</label>
                <input
                  id="oobe-display-name"
                  type="text"
                  className="login-input"
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                />
              </div>

              <div className="login-field">
                <label className="login-label" htmlFor="oobe-password">Password</label>
                <input
                  id="oobe-password"
                  type="password"
                  className="login-input"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
              </div>

              <div className="login-field">
                <label className="login-label" htmlFor="oobe-password-confirm">Confirm Password</label>
                <input
                  id="oobe-password-confirm"
                  type="password"
                  className="login-input"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  required
                />
              </div>

              <ul className="oobe-rules">
                {RULES.map((rule) => (
                  <li key={rule.label} className={rule.test(password) ? 'pass' : ''}>
                    {rule.test(password) ? '✓' : '✗'} {rule.label}
                  </li>
                ))}
                {confirmPassword && (
                  <li className={passwordsMatch ? 'pass' : ''}>
                    {passwordsMatch ? '✓' : '✗'} Passwords match
                  </li>
                )}
              </ul>

              <div className="oobe-actions">
                <button type="button" className="btn btn-secondary" onClick={goBack}>Back</button>
                <button type="submit" className="btn btn-primary">Next</button>
              </div>
            </form>
          )}

          {step === 3 && (
            <>
              <h2 className="login-card-title">Choose your theme</h2>
              <p className="login-card-subtitle">Pick a palette and mode. You can change either anytime in Settings.</p>

              {/* Dark / Light mode toggle */}
              <div className="oobe-mode-row">
                <span className="login-label" style={{ marginBottom: 0 }}>Mode</span>
                <fieldset className="oobe-mode-toggle" aria-label="Color mode" style={{ border: 'none', padding: 0, margin: 0 }}>
                  <button
                    type="button"
                    className={`oobe-mode-btn${selectedThemeMode === 'dark' ? ' active' : ''}`}
                    onClick={() => selectMode('dark')}
                  >
                    <Moon size={13} />
                    Dark
                  </button>
                  <button
                    type="button"
                    className={`oobe-mode-btn${selectedThemeMode === 'light' ? ' active' : ''}`}
                    onClick={() => selectMode('light')}
                  >
                    <Sun size={13} />
                    Light
                  </button>
                </fieldset>
              </div>

              <div className="oobe-theme-grid">
                {PRESET_KEYS.map((key) => {
                  const variant = THEME_PRESETS[key]?.[selectedThemeMode] ?? THEME_PRESETS[key]?.dark;
                  return (
                    <button
                      key={key}
                      type="button"
                      className={`oobe-theme-tile${selectedPreset === key ? ' active' : ''}`}
                      onClick={() => selectPreset(key)}
                    >
                      <span className="oobe-theme-name">{PRESET_LABELS[key] ?? key}</span>
                      <span className="oobe-theme-preview" style={{ background: variant?.background || 'var(--color-surface)' }}>
                        <span style={{ background: variant?.surface || 'var(--color-surface-alt)' }} />
                        <span style={{ background: variant?.primary || 'var(--color-primary)' }} />
                        <span style={{ background: variant?.accent1 || 'var(--accent-1)' }} />
                      </span>
                    </button>
                  );
                })}
              </div>

              <div style={{ marginTop: 16 }}>
                <label className="login-label" htmlFor="oobe-font-family">Font Family</label>
                <select
                  id="oobe-font-family"
                  className="form-control"
                  value={selectedFont}
                  onChange={(e) => {
                    const nextFont = e.target.value;
                    setSelectedFont(nextFont);
                    applyFontInstant(nextFont, selectedFontSize);
                  }}
                >
                  {FONT_OPTIONS.map((fontOption) => (
                    <option key={fontOption.id} value={fontOption.id}>{fontOption.label}</option>
                  ))}
                </select>
              </div>

              <div style={{ marginTop: 12 }}>
                <label className="login-label" htmlFor="oobe-font-size-options">Font Size</label>
                <div id="oobe-font-size-options" style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                  {FONT_SIZE_OPTIONS.map((sizeOption) => (
                    <button
                      key={sizeOption.id}
                      type="button"
                      className={`btn btn-sm ${selectedFontSize === sizeOption.id ? 'btn-primary' : 'btn-secondary'}`}
                      onClick={() => {
                        setSelectedFontSize(sizeOption.id);
                        applyFontInstant(selectedFont, sizeOption.id);
                      }}
                      title={`${sizeOption.rootPx}px base`}
                    >
                      {sizeOption.label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="oobe-actions">
                <button type="button" className="btn btn-secondary" onClick={goBack}>Back</button>
                <button type="button" className="btn btn-primary" onClick={goNext}>Next</button>
              </div>
            </>
          )}

          {step === 4 && (
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
                    {locationSearching ? <Search size={13} className="oobe-location-spin" /> : <MapPin size={13} />}
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
                    {timezone !== 'UTC' && <> · Timezone set to <strong>{timezone}</strong></>}
                  </p>
                )}
              </div>

              <div style={{ margin: '16px 0 12px' }}>
                <label className="login-label" htmlFor="oobe-language">Preferred Language</label>
                <select
                  id="oobe-language"
                  className="form-control"
                  value={language}
                  onChange={(e) => setLanguage(e.target.value)}
                >
                  {languages.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </div>

              <div style={{ margin: '0 0 8px' }}>
                <TimezoneSelect
                  value={timezone}
                  onChange={handleTimezoneChange}
                />
              </div>

              <p style={{ fontSize: '0.7rem', color: 'var(--color-text-muted)', margin: '4px 0 0' }}>
                All of these can be changed anytime in Settings → General.
              </p>
              <div className="oobe-actions">
                <button type="button" className="btn btn-secondary" onClick={goBack}>Back</button>
                <button type="button" className="btn btn-primary" onClick={goNext}>Continue →</button>
              </div>
            </>
          )}

          {step === 5 && (
            <>
              <h2 className="login-card-title">Confirmation</h2>
              <p className="login-card-subtitle">Review and complete setup.</p>

              <div className="oobe-summary">
                <img src={sanitizeImageSrc(photoPreview || gravatarPreview)} alt="Avatar preview" className="oobe-avatar" />
                <div className="oobe-summary-details">
                  <div className="oobe-summary-email">{email}</div>
                  <div><strong>Display Name:</strong> {displayName || '(auto from email)'}</div>
                  <div><strong>Theme:</strong> {PRESET_LABELS[selectedPreset] ?? selectedPreset} ({selectedThemeMode})</div>
                  <div><strong>Font:</strong> {FONT_OPTIONS.find((entry) => entry.id === selectedFont)?.label ?? selectedFont} · {FONT_SIZE_OPTIONS.find((entry) => entry.id === selectedFontSize)?.label ?? selectedFontSize}</div>
                  <div><strong>Language:</strong> {languages.find((entry) => entry.value === language)?.label ?? language}</div>
                  <div><strong>Timezone:</strong> {timezone}</div>
                  {(weatherLocation || timezoneToCity(timezone)) && (
                    <div><strong>Weather:</strong> {weatherLocation || timezoneToCity(timezone)}</div>
                  )}
                </div>
              </div>

              <div className="oobe-actions">
                <button type="button" className="btn btn-secondary" onClick={goBack} disabled={submitting}>Back</button>
                <button type="button" className="btn btn-primary" onClick={submitBootstrap} disabled={submitting}>
                  {submitting ? 'Creating…' : 'Create account and enter Circuit Breaker'}
                </button>
              </div>
            </>
          )}

          {error && <div className="login-error-banner" role="alert">{error}</div>}
        </div>

        {/* Desktop / tablet hint — 3rd column, hidden on mobile */}
        {step === 2 && (
          <div className="oobe-hint-desktop-wrap">{avatarHintCard}</div>
        )}
        {step === 3 && (
          <div className="oobe-hint-desktop-wrap">{themeHintCard}</div>
        )}
        {step === 4 && (
          <div className="oobe-hint-desktop-wrap">{regionalHintCard}</div>
        )}
        </div>{/* end oobe-step3-row */}
      </div>
    </div>
  );

}

OOBEWizardPage.propTypes = {
  onCompleted: PropTypes.func,
};

export default OOBEWizardPage;
