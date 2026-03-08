import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  Moon,
  Sun,
  Sparkles,
  UserCircle2,
  X,
  MapPin,
  Search,
  ShieldAlert,
  Copy,
  Download,
  CheckCircle2,
  Lock,
  ExternalLink,
} from 'lucide-react';
import { authApi } from '../api/auth.js';
import apiClient from '../api/client';
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
  const location = useLocation();
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
  const [weatherLocation, setWeatherLocation] = useState(() =>
    timezoneToCity(Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC')
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
  // Vault key ceremony state — populated when bootstrap returns vault_key_warning: true
  const [vaultKey, setVaultKey] = useState(null);
  const [vaultKeyAcked, setVaultKeyAcked] = useState(false);
  const [vaultKeyCopied, setVaultKeyCopied] = useState(false);
  // Pending navigation payload — stored while vault key modal is open
  const pendingNavRef = useRef(null);
  const [smtpEnabled, setSmtpEnabled] = useState(false);
  const [smtpHost, setSmtpHost] = useState('');
  const [smtpPort, setSmtpPort] = useState('587');
  const [smtpUsername, setSmtpUsername] = useState('');
  const [smtpPassword, setSmtpPassword] = useState('');
  const [smtpFromEmail, setSmtpFromEmail] = useState('');
  const [smtpFromName, setSmtpFromName] = useState('Circuit Breaker');
  const [smtpTls, setSmtpTls] = useState(true);
  const [externalAppUrl, setExternalAppUrl] = useState(settings?.api_base_url ?? '');

  // OAuth bootstrap state — set when returning from OAuth redirect with ?bootstrap=1
  const [oauthBootstrapToken, setOauthBootstrapToken] = useState(null);
  const [oauthBootstrapEmail, setOauthBootstrapEmail] = useState(null);
  const [oauthBootstrapProvider, setOauthBootstrapProvider] = useState(null);
  // OAuth provider setup sub-form
  const [oauthSetupMode, setOauthSetupMode] = useState(false);
  const [oauthSetupProvider, setOauthSetupProvider] = useState('github');
  const [oauthSetupClientId, setOauthSetupClientId] = useState('');
  const [oauthSetupClientSecret, setOauthSetupClientSecret] = useState('');
  const [oauthSetupDiscoveryUrl, setOauthSetupDiscoveryUrl] = useState('');
  const [oauthSetupSaving, setOauthSetupSaving] = useState(false);

  const languages = [
    { value: 'en', label: 'English' },
    { value: 'es', label: 'Español' },
    { value: 'fr', label: 'Français' },
    { value: 'de', label: 'Deutsch' },
    { value: 'zh', label: '中文 (简体)' },
    { value: 'ja', label: '日本語' },
  ];

  // ── Caddy HTTPS detection ────────────────────────────────────────────────
  // Detect when the user is behind Caddy (HTTPS on a non-dev host).
  // Port 5173 = Vite dev, 8080/8000 = direct nginx/backend, no Caddy.
  const _caddyDetection = useMemo(() => {
    const { hostname, protocol, port } = window.location;
    const isDevHost =
      hostname === 'localhost' ||
      hostname === '127.0.0.1' ||
      port === '5173' ||
      port === '8080' ||
      port === '8000';
    if (isDevHost) return { active: false };
    const isHttps = protocol === 'https:';
    const isHttp80 = protocol === 'http:' && port === '';
    if (!isHttps && !isHttp80) return { active: false };
    const httpsOrigin = `https://${hostname}`;
    const certUrl = `http://${hostname}/caddy-root-ca.crt`;
    return { active: true, isHttps, httpsOrigin, certUrl };
  }, []);

  // Auto-populate external app URL when running behind Caddy and field is empty.
  useEffect(() => {
    if (step === 5 && !externalAppUrl && _caddyDetection.active) {
      setExternalAppUrl(_caddyDetection.httpsOrigin);
    }
  }, [step]); // eslint-disable-line react-hooks/exhaustive-deps

  const handlePhotoFile = (e) => {
    const f = e.target.files[0];
    if (!f) return;
    if (f.size > 10 * 1024 * 1024) {
      setError('Photo must be ≤ 10 MB.');
      return;
    }
    if (!['image/jpeg', 'image/png'].includes(f.type)) {
      setError('Photo must be JPEG or PNG.');
      return;
    }
    setError('');
    setPhotoFile(f);
    setPhotoPreview(URL.createObjectURL(f));
  };

  const clearPhoto = () => {
    setPhotoFile(null);
    setPhotoPreview(null);
    if (photoFileRef.current) photoFileRef.current.value = '';
  };

  // Force the default theme on mount so the OOBE always starts with the
  // correct visual regardless of what SettingsContext loaded from the API.
  useEffect(() => {
    document.documentElement.dataset.theme = selectedThemeMode;
    applyTheme(THEME_PRESETS[DEFAULT_PRESET], DEFAULT_PRESET);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Detect OAuth bootstrap return: /oobe?oauth_token=...&bootstrap=1&provider=...
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const oauthToken = params.get('oauth_token');
    const isBootstrap = params.get('bootstrap') === '1';
    if (!oauthToken || !isBootstrap) return;

    // Restore in-progress OOBE state saved before the OAuth redirect
    try {
      const saved = JSON.parse(sessionStorage.getItem('oobe_state') || '{}');
      if (saved.selectedPreset) setSelectedPreset(saved.selectedPreset);
      if (saved.selectedThemeMode) setSelectedThemeMode(saved.selectedThemeMode);
      if (saved.timezone) setTimezone(saved.timezone);
      if (saved.language) setLanguage(saved.language);
      if (saved.selectedFont) setSelectedFont(saved.selectedFont);
      if (saved.selectedFontSize) setSelectedFontSize(saved.selectedFontSize);
      if (saved.weatherLocation) setWeatherLocation(saved.weatherLocation);
      if (saved.externalAppUrl) setExternalAppUrl(saved.externalAppUrl);
    } catch {
      // Ignore parse errors — defaults are fine
    }
    sessionStorage.removeItem('oobe_state');

    setOauthBootstrapToken(oauthToken);
    setOauthBootstrapProvider(params.get('provider') || 'oauth');

    // Fetch the user profile to display their email in the confirmation banner
    authApi
      .meWithToken(oauthToken)
      .then((res) => setOauthBootstrapEmail(res.data?.email || null))
      .catch(() => {});

    // Clean token from URL without triggering a re-render loop
    globalThis.history.replaceState({}, '', '/oobe');
    // Skip account creation step — go straight to theme
    setStep(3);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

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
  const smtpFromEmailValid = !smtpEnabled || EMAIL_RE.test(smtpFromEmail);

  const validateSmtpStep = () => {
    if (/\s/.test(externalAppUrl.trim())) {
      return 'External app URL cannot contain spaces.';
    }
    if (!smtpEnabled) return null;
    if (!smtpHost.trim()) return 'SMTP host is required when email delivery is enabled.';
    if (!smtpFromEmail.trim()) return 'SMTP from email is required when email delivery is enabled.';
    if (!smtpFromEmailValid) return 'Enter a valid SMTP from email address.';
    const parsedPort = Number(smtpPort);
    if (!Number.isInteger(parsedPort) || parsedPort < 1 || parsedPort > 65535) {
      return 'SMTP port must be between 1 and 65535.';
    }
    return null;
  };

  const goNext = () => {
    if (step === 2 && !oauthBootstrapToken && !accountValid) {
      setError('Please fix account validation errors before continuing.');
      return;
    }
    if (step === 5) {
      const smtpError = validateSmtpStep();
      if (smtpError) {
        setError(smtpError);
        return;
      }
    }
    setError('');
    setStep((value) => Math.min(6, value + 1));
  };

  const goBack = () => {
    setError('');
    setStep((value) => Math.max(1, value - 1));
  };

  const applyFontInstant = (fontId, fontSizeId) => {
    const font =
      FONT_OPTIONS.find((entry) => entry.id === fontId) ??
      FONT_OPTIONS.find((entry) => entry.id === 'inter') ??
      FONT_OPTIONS[0];
    const size =
      FONT_SIZE_OPTIONS.find((entry) => entry.id === fontSizeId) ??
      FONT_SIZE_OPTIONS.find((entry) => entry.id === 'medium') ??
      FONT_SIZE_OPTIONS[0];

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

  const handleOauthSignup = async () => {
    if (!oauthSetupClientId.trim() || !oauthSetupClientSecret.trim()) {
      setError('Client ID and Client Secret are required.');
      return;
    }
    if (oauthSetupProvider === 'oidc' && !oauthSetupDiscoveryUrl.trim()) {
      setError('Discovery URL is required for OIDC.');
      return;
    }
    setError('');
    setOauthSetupSaving(true);
    try {
      // Persist provider config to backend before redirecting
      if (oauthSetupProvider === 'oidc') {
        const existing = await apiClient
          .get('/settings/oauth')
          .then((r) => r.data.oidc_providers || []);
        const newEntry = {
          slug: 'oidc',
          name: 'oidc',
          label: 'OIDC',
          enabled: true,
          client_id: oauthSetupClientId.trim(),
          client_secret: oauthSetupClientSecret.trim(),
          discovery_url: oauthSetupDiscoveryUrl.trim(),
        };
        const merged = [...existing.filter((p) => p.slug !== 'oidc'), newEntry];
        await apiClient.patch('/settings/oauth', { oidc_providers: merged });
      } else {
        await apiClient.patch('/settings/oauth', {
          oauth_providers: {
            [oauthSetupProvider]: {
              enabled: true,
              client_id: oauthSetupClientId.trim(),
              client_secret: oauthSetupClientSecret.trim(),
            },
          },
        });
      }
    } catch {
      setError('Failed to save OAuth provider settings. Please try again.');
      setOauthSetupSaving(false);
      return;
    }

    // Save in-progress OOBE state so it survives the OAuth redirect
    sessionStorage.setItem(
      'oobe_state',
      JSON.stringify({
        selectedPreset,
        selectedThemeMode,
        timezone,
        language,
        selectedFont,
        selectedFontSize,
        weatherLocation,
        externalAppUrl,
      })
    );

    // Navigate to OAuth authorize endpoint (full-page redirect)
    if (oauthSetupProvider === 'oidc') {
      globalThis.location.href = '/api/v1/auth/oauth/oidc/oidc';
    } else {
      globalThis.location.href = `/api/v1/auth/oauth/${oauthSetupProvider}`;
    }
  };

  const submitBootstrap = async () => {
    const localAccountRequired = !oauthBootstrapToken;
    if (localAccountRequired && !accountValid) {
      setStep(2);
      setError('Account details are invalid.');
      return;
    }
    setSubmitting(true);
    setError('');
    try {
      const sharedSettings = {
        theme_preset: selectedPreset,
        api_base_url: externalAppUrl.trim() || undefined,
        theme: selectedThemeMode,
        timezone,
        language,
        ui_font: selectedFont,
        ui_font_size: selectedFontSize,
        weather_location: weatherLocation || timezoneToCity(timezone) || undefined,
        ...(smtpEnabled
          ? {
              smtp_enabled: true,
              smtp_host: smtpHost.trim(),
              smtp_port: Number(smtpPort) || 587,
              smtp_username: smtpUsername.trim() || undefined,
              smtp_password: smtpPassword || undefined,
              smtp_from_email: smtpFromEmail.trim(),
              smtp_from_name: smtpFromName.trim() || 'Circuit Breaker',
              smtp_tls: smtpTls,
            }
          : {}),
      };

      let response;
      if (oauthBootstrapToken) {
        response = await authApi.bootstrapInitializeOAuth({
          oauth_token: oauthBootstrapToken,
          display_name: displayName || undefined,
          ...sharedSettings,
        });
      } else {
        response = await authApi.bootstrapInitialize({
          email,
          password,
          display_name: displayName || undefined,
          ...sharedSettings,
        });
      }

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

      if (response.data.vault_key_warning && response.data.vault_key) {
        // Store vault key for ceremony step — don't navigate yet
        pendingNavRef.current = { onCompleted, navigate };
        setVaultKey(response.data.vault_key);
        return;
      }

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

  const handleVaultKeyCopy = async () => {
    try {
      await navigator.clipboard.writeText(vaultKey);
      setVaultKeyCopied(true);
      setTimeout(() => setVaultKeyCopied(false), 2500);
    } catch {
      // Fallback: select the textarea text
    }
  };

  const handleVaultKeyDownload = () => {
    const content = `# Circuit Breaker Vault Key — generated during OOBE\n# Keep this file safe. Loss means permanent credential loss.\nCB_VAULT_KEY=${vaultKey}\n`;
    const blob = new Blob([content], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'cb-vault-key.env';
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleVaultKeyContinue = () => {
    setVaultKey(null);
    setVaultKeyAcked(false);
    setVaultKeyCopied(false);
    const pending = pendingNavRef.current;
    pendingNavRef.current = null;
    pending?.onCompleted?.();
    pending?.navigate('/map', { replace: true });
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

  const avatarHintCard = (
    <div className="oobe-hint-card">
      <div className="oobe-hint-header">
        <UserCircle2 size={16} className="oobe-hint-icon" />
        <span>Profile Photo</span>
      </div>
      <p className="oobe-hint-body">
        Your avatar is pulled automatically from <strong>Gravatar</strong> using your email address
        — no upload needed.
      </p>
      <ul className="oobe-hint-combos">
        <li>
          <span className="oobe-hint-swatch" style={{ background: 'var(--color-primary)' }} />
          Type your email and the preview updates live
        </li>
        <li>
          <span className="oobe-hint-swatch" style={{ background: 'var(--color-text-muted)' }} />
          No Gravatar? Click the photo to upload your own JPEG or PNG
        </li>
        <li>
          <span className="oobe-hint-swatch" style={{ background: 'var(--color-online)' }} />
          Custom upload always takes priority over Gravatar
        </li>
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
        Every theme has both a <strong>dark</strong> and <strong>light</strong> variant. Use the
        toggle above to flip modes as you try presets — your perfect combination is out there.
      </p>
      <ul className="oobe-hint-combos">
        <li>
          <span className="oobe-hint-swatch" style={{ background: '#00f5ff' }} />
          Cyberpunk Neon + Dark — high-contrast night
        </li>
        <li>
          <span className="oobe-hint-swatch" style={{ background: '#8be9fd' }} />
          Dracula + Light — soft pastel daytime
        </li>
        <li>
          <span className="oobe-hint-swatch" style={{ background: '#a9dc76' }} />
          Monokai + Dark — warm retro terminal
        </li>
        <li>
          <span className="oobe-hint-swatch" style={{ background: '#b48ead' }} />
          Nord + Light — calm Nordic workspace
        </li>
      </ul>
      <p className="oobe-hint-tip">
        💡 You can change your theme and mode any time from the header or{' '}
        <em>Settings → Appearance</em>.
      </p>
    </div>
  );

  // Vault key ceremony overlay — shown after bootstrap when key is generated
  if (vaultKey) {
    return (
      <div className="login-root">
        <div className="login-bokeh-tl" aria-hidden="true" />
        <div className="login-bokeh-br" aria-hidden="true" />
        <div className="oobe-layout">
          <div className="oobe-header">
            <img
              src={branding?.login_logo_path ?? '/CB-AZ_Final.png'}
              alt={branding?.app_name ?? 'Circuit Breaker'}
            />
            <div className="login-status" style={{ marginTop: 4 }}>
              <span className="login-status-dot status-indicator--online" aria-hidden="true" />{' '}
              First-run setup
            </div>
          </div>
          <div className="oobe-step3-row">
            <div className="login-card oobe-card" style={{ maxWidth: 560 }}>
              <div className="oobe-progress">Step 7/7</div>

              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
                <ShieldAlert
                  size={22}
                  style={{ color: 'var(--color-danger, #f85149)', flexShrink: 0 }}
                />
                <h2
                  className="login-card-title"
                  style={{ margin: 0, color: 'var(--color-danger, #f85149)' }}
                >
                  Critical: Back Up Your Vault Key
                </h2>
              </div>

              <p className="login-card-subtitle" style={{ marginBottom: 12 }}>
                Circuit Breaker generated a vault key to encrypt all secrets (SNMP, SSH, SMTP
                passwords). This key is stored in the persistent volume, but you must back it up
                now. If you enable SMTP, email reset becomes the convenience path, but this vault
                key remains your offline recovery fallback.
                <strong> It will never be shown again.</strong>
              </p>

              <div style={{ marginBottom: 12 }}>
                <label className="login-label" style={{ marginBottom: 6, display: 'block' }}>
                  Your Vault Key
                </label>
                <div
                  style={{
                    position: 'relative',
                    background: 'var(--color-surface)',
                    border: '1px solid var(--color-border)',
                    borderRadius: 6,
                    padding: '10px 12px',
                    fontFamily: 'monospace',
                    fontSize: '0.78rem',
                    wordBreak: 'break-all',
                    color: 'var(--color-text)',
                    userSelect: 'all',
                  }}
                >
                  <span style={{ color: 'var(--color-text-muted)' }}>CB_VAULT_KEY=</span>
                  {vaultKey}
                </div>
              </div>

              <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={handleVaultKeyCopy}
                  style={{ display: 'flex', alignItems: 'center', gap: 6 }}
                >
                  {vaultKeyCopied ? <CheckCircle2 size={14} /> : <Copy size={14} />}
                  {vaultKeyCopied ? 'Copied!' : 'Copy Key'}
                </button>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={handleVaultKeyDownload}
                  style={{ display: 'flex', alignItems: 'center', gap: 6 }}
                >
                  <Download size={14} />
                  Download .env snippet
                </button>
              </div>

              <div
                style={{
                  background: 'color-mix(in srgb, var(--color-danger, #f85149) 10%, transparent)',
                  border:
                    '1px solid color-mix(in srgb, var(--color-danger, #f85149) 30%, transparent)',
                  borderRadius: 6,
                  padding: '10px 14px',
                  fontSize: '0.78rem',
                  marginBottom: 16,
                  lineHeight: 1.6,
                }}
              >
                <strong>Where to store it:</strong>
                <ul style={{ margin: '4px 0 0', paddingLeft: 20 }}>
                  <li>Password manager or secure notes vault</li>
                  <li>
                    The <code>/data/.env</code> file in your Docker volume (already written)
                  </li>
                  <li>Offline in a secure location</li>
                </ul>
                <strong style={{ color: 'var(--color-danger, #f85149)' }}>
                  Loss = permanent loss of all encrypted credentials. No recovery possible.
                </strong>
              </div>

              <label
                style={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: 10,
                  cursor: 'pointer',
                  marginBottom: 20,
                }}
              >
                <input
                  type="checkbox"
                  checked={vaultKeyAcked}
                  onChange={(e) => setVaultKeyAcked(e.target.checked)}
                  style={{
                    marginTop: 2,
                    accentColor: 'var(--color-primary)',
                    width: 16,
                    height: 16,
                    flexShrink: 0,
                  }}
                />
                <span style={{ fontSize: '0.85rem' }}>
                  I have securely backed up my vault key and understand it cannot be recovered if
                  lost.
                </span>
              </label>

              <div className="oobe-actions">
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={handleVaultKeyContinue}
                  disabled={!vaultKeyAcked}
                >
                  Continue to Circuit Breaker
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="login-root">
      <div className="login-bokeh-tl" aria-hidden="true" />
      <div className="login-bokeh-br" aria-hidden="true" />
      <div
        className={`oobe-layout${step === 2 || step === 3 || step === 4 ? ' oobe-layout--theme-step' : ''}`}
      >
        <div className="oobe-header">
          <img
            src={branding?.login_logo_path ?? '/CB-AZ_Final.png'}
            alt={branding?.app_name ?? 'Circuit Breaker'}
          />
          {/* Brand name removed - logo is sufficient */}
          <div className="login-status" style={{ marginTop: 4 }}>
            <span className="login-status-dot status-indicator--online" aria-hidden="true" />{' '}
            First-run setup
          </div>
        </div>

        {/* Mobile hint — shown above the card on relevant steps */}
        {step === 2 && <div className="oobe-hint-mobile-wrap">{avatarHintCard}</div>}
        {step === 3 && <div className="oobe-hint-mobile-wrap">{themeHintCard}</div>}
        {step === 4 && <div className="oobe-hint-mobile-wrap">{regionalHintCard}</div>}

        <div
          className={`oobe-step3-row${step === 2 || step === 3 || step === 4 ? ' oobe-step3-row--active' : ''}`}
        >
          <div className="login-card oobe-card">
            <div className="oobe-progress">Step {step}/6</div>

            {step === 1 && (
              <>
                {/* Card title removed - logo and context are sufficient */}
                <p className="login-card-subtitle">
                  Let’s create your first admin account and personalize your dashboard.
                </p>
                <div className="oobe-actions">
                  <button
                    type="button"
                    className="btn btn-primary login-btn-submit"
                    onClick={goNext}
                  >
                    Get Started
                  </button>
                </div>
              </>
            )}

            {step === 2 && (
              <div>
                <h2 className="login-card-title">Create Account</h2>
                <p className="login-card-subtitle">
                  Create the first admin account for this installation.
                </p>

                {/* ── OAuth confirmation banner (shown after returning from OAuth) ── */}
                {oauthBootstrapToken && (
                  <div
                    style={{
                      background: 'var(--color-surface-2, var(--color-surface))',
                      border: '1px solid var(--color-online)',
                      borderRadius: '0.5rem',
                      padding: '0.875rem 1rem',
                      marginBottom: '1rem',
                    }}
                  >
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.5rem',
                        marginBottom: '0.375rem',
                      }}
                    >
                      <CheckCircle2
                        size={16}
                        style={{ color: 'var(--color-online)', flexShrink: 0 }}
                      />
                      <span style={{ fontSize: '0.875rem', fontWeight: 600 }}>
                        Signed in via {oauthBootstrapProvider || 'OAuth'}
                      </span>
                    </div>
                    {oauthBootstrapEmail && (
                      <p
                        style={{
                          fontSize: '0.8125rem',
                          color: 'var(--color-text-muted)',
                          margin: '0 0 0.5rem 1.5rem',
                        }}
                      >
                        {oauthBootstrapEmail}
                      </p>
                    )}
                    <button
                      type="button"
                      className="btn btn-secondary"
                      style={{
                        fontSize: '0.75rem',
                        padding: '0.25rem 0.625rem',
                        marginLeft: '1.5rem',
                      }}
                      onClick={() => {
                        setOauthBootstrapToken(null);
                        setOauthBootstrapEmail(null);
                        setOauthBootstrapProvider(null);
                      }}
                    >
                      Change account
                    </button>
                  </div>
                )}

                {/* ── Local sign-up form + OAuth alternative (hidden when OAuth bootstrap is active) ── */}
                {!oauthBootstrapToken && (
                  <>
                    <form
                      onSubmit={(event) => {
                        event.preventDefault();
                        goNext();
                      }}
                      noValidate
                    >
                      <div className="oobe-avatar-wrap">
                        <button
                          type="button"
                          className="oobe-avatar-btn"
                          onClick={() => photoFileRef.current?.click()}
                          title="Upload profile photo (optional)"
                        >
                          <img
                            src={sanitizeImageSrc(photoPreview || gravatarPreview)}
                            alt="Avatar preview"
                            className="oobe-avatar"
                          />
                          <span className="oobe-avatar-overlay" aria-hidden="true">
                            📷
                          </span>
                        </button>
                        {photoFile ? (
                          <div className="oobe-avatar-status">
                            <span className="oobe-avatar-status-text">✓ Custom photo ready</span>
                            <button
                              type="button"
                              className="oobe-avatar-clear"
                              onClick={clearPhoto}
                              title="Remove custom photo"
                            >
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
                        <label className="login-label" htmlFor="oobe-email">
                          Email
                        </label>
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
                        <label className="login-label" htmlFor="oobe-display-name">
                          Display Name (optional)
                        </label>
                        <input
                          id="oobe-display-name"
                          type="text"
                          className="login-input"
                          value={displayName}
                          onChange={(e) => setDisplayName(e.target.value)}
                        />
                      </div>

                      <div className="login-field">
                        <label className="login-label" htmlFor="oobe-password">
                          Password
                        </label>
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
                        <label className="login-label" htmlFor="oobe-password-confirm">
                          Confirm Password
                        </label>
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
                        <button type="button" className="btn btn-secondary" onClick={goBack}>
                          Back
                        </button>
                        <button type="submit" className="btn btn-primary">
                          Next
                        </button>
                      </div>
                    </form>

                    {/* ── OAuth alternative ── */}
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.75rem',
                        margin: '1.25rem 0 1rem',
                      }}
                    >
                      <hr
                        style={{
                          flex: 1,
                          border: 'none',
                          borderTop: '1px solid var(--color-border)',
                        }}
                      />
                      <span
                        style={{
                          fontSize: '0.75rem',
                          color: 'var(--color-text-muted)',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        OR
                      </span>
                      <hr
                        style={{
                          flex: 1,
                          border: 'none',
                          borderTop: '1px solid var(--color-border)',
                        }}
                      />
                    </div>

                    {!oauthSetupMode ? (
                      <div style={{ textAlign: 'center' }}>
                        <p
                          style={{
                            fontSize: '0.8125rem',
                            color: 'var(--color-text-muted)',
                            marginBottom: '0.625rem',
                          }}
                        >
                          Sign up with an OAuth provider instead
                        </p>
                        <div
                          style={{
                            display: 'flex',
                            justifyContent: 'center',
                            gap: '0.5rem',
                            flexWrap: 'wrap',
                          }}
                        >
                          {[
                            { id: 'github', label: 'GitHub' },
                            { id: 'google', label: 'Google' },
                            { id: 'oidc', label: 'OIDC' },
                          ].map(({ id, label }) => (
                            <button
                              key={id}
                              type="button"
                              className="btn btn-secondary"
                              style={{ fontSize: '0.8125rem', padding: '0.375rem 0.875rem' }}
                              onClick={() => {
                                setOauthSetupProvider(id);
                                setOauthSetupMode(true);
                                setError('');
                              }}
                            >
                              {label}
                            </button>
                          ))}
                        </div>
                      </div>
                    ) : (
                      <div>
                        <div
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            marginBottom: '0.75rem',
                          }}
                        >
                          <span style={{ fontSize: '0.875rem', fontWeight: 600 }}>
                            Sign up with{' '}
                            {{ github: 'GitHub', google: 'Google', oidc: 'OIDC' }[
                              oauthSetupProvider
                            ] || oauthSetupProvider}
                          </span>
                          <button
                            type="button"
                            className="btn btn-secondary"
                            style={{ fontSize: '0.75rem', padding: '0.25rem 0.5rem' }}
                            onClick={() => {
                              setOauthSetupMode(false);
                              setOauthSetupClientId('');
                              setOauthSetupClientSecret('');
                              setOauthSetupDiscoveryUrl('');
                              setError('');
                            }}
                          >
                            Cancel
                          </button>
                        </div>

                        <div className="login-field">
                          <label className="login-label" htmlFor="oobe-oauth-client-id">
                            Client ID
                          </label>
                          <input
                            id="oobe-oauth-client-id"
                            type="text"
                            className="login-input"
                            value={oauthSetupClientId}
                            onChange={(e) => setOauthSetupClientId(e.target.value)}
                            autoComplete="off"
                          />
                        </div>

                        <div className="login-field">
                          <label className="login-label" htmlFor="oobe-oauth-client-secret">
                            Client Secret
                          </label>
                          <input
                            id="oobe-oauth-client-secret"
                            type="password"
                            className="login-input"
                            value={oauthSetupClientSecret}
                            onChange={(e) => setOauthSetupClientSecret(e.target.value)}
                            autoComplete="new-password"
                          />
                        </div>

                        {oauthSetupProvider === 'oidc' && (
                          <div className="login-field">
                            <label className="login-label" htmlFor="oobe-oauth-discovery-url">
                              Discovery URL
                            </label>
                            <input
                              id="oobe-oauth-discovery-url"
                              type="url"
                              className="login-input"
                              placeholder="https://auth.example.com/.well-known/openid-configuration"
                              value={oauthSetupDiscoveryUrl}
                              onChange={(e) => setOauthSetupDiscoveryUrl(e.target.value)}
                            />
                          </div>
                        )}

                        <div className="login-field">
                          <label className="login-label" htmlFor="oobe-oauth-redirect-uri">
                            Callback / Redirect URI
                          </label>
                          <div style={{ display: 'flex', gap: '0.375rem', alignItems: 'center' }}>
                            <input
                              id="oobe-oauth-redirect-uri"
                              type="text"
                              className="login-input"
                              readOnly
                              value={
                                oauthSetupProvider === 'oidc'
                                  ? `${globalThis.location.origin}/api/v1/auth/oauth/oidc/oidc/callback`
                                  : `${globalThis.location.origin}/api/v1/auth/oauth/${oauthSetupProvider}/callback`
                              }
                              style={{ flex: 1, cursor: 'text' }}
                            />
                            <button
                              type="button"
                              className="btn btn-secondary"
                              style={{ padding: '0.375rem 0.5rem', flexShrink: 0 }}
                              title="Copy"
                              onClick={() => {
                                const uri =
                                  oauthSetupProvider === 'oidc'
                                    ? `${globalThis.location.origin}/api/v1/auth/oauth/oidc/oidc/callback`
                                    : `${globalThis.location.origin}/api/v1/auth/oauth/${oauthSetupProvider}/callback`;
                                navigator.clipboard.writeText(uri).catch(() => {});
                              }}
                            >
                              <Copy size={13} />
                            </button>
                          </div>
                          <p
                            style={{
                              fontSize: '0.75rem',
                              color: 'var(--color-text-muted)',
                              marginTop: '0.25rem',
                            }}
                          >
                            Register this URL as an authorized redirect URI in your OAuth app.
                          </p>
                        </div>

                        <div style={{ marginTop: '0.75rem' }}>
                          <button
                            type="button"
                            className="btn btn-primary login-btn-submit"
                            disabled={oauthSetupSaving}
                            onClick={handleOauthSignup}
                          >
                            {oauthSetupSaving
                              ? 'Saving…'
                              : `Continue with ${{ github: 'GitHub', google: 'Google', oidc: 'OIDC' }[oauthSetupProvider] || oauthSetupProvider}`}
                          </button>
                        </div>
                      </div>
                    )}
                  </>
                )}

                {/* ── Nav buttons when returning from OAuth (local form is bypassed) ── */}
                {oauthBootstrapToken && (
                  <div className="oobe-actions">
                    <button type="button" className="btn btn-secondary" onClick={goBack}>
                      Back
                    </button>
                    <button type="button" className="btn btn-primary" onClick={goNext}>
                      Next
                    </button>
                  </div>
                )}
              </div>
            )}

            {step === 3 && (
              <>
                <h2 className="login-card-title">Choose your theme</h2>
                <p className="login-card-subtitle">
                  Pick a palette and mode. You can change either anytime in Settings.
                </p>

                {/* Dark / Light mode toggle */}
                <div className="oobe-mode-row">
                  <span className="login-label" style={{ marginBottom: 0 }}>
                    Mode
                  </span>
                  <fieldset
                    className="oobe-mode-toggle"
                    aria-label="Color mode"
                    style={{ border: 'none', padding: 0, margin: 0 }}
                  >
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
                    const variant =
                      THEME_PRESETS[key]?.[selectedThemeMode] ?? THEME_PRESETS[key]?.dark;
                    return (
                      <button
                        key={key}
                        type="button"
                        className={`oobe-theme-tile${selectedPreset === key ? ' active' : ''}`}
                        onClick={() => selectPreset(key)}
                      >
                        <span className="oobe-theme-name">{PRESET_LABELS[key] ?? key}</span>
                        <span
                          className="oobe-theme-preview"
                          style={{ background: variant?.background || 'var(--color-surface)' }}
                        >
                          <span
                            style={{ background: variant?.surface || 'var(--color-surface-alt)' }}
                          />
                          <span
                            style={{ background: variant?.primary || 'var(--color-primary)' }}
                          />
                          <span style={{ background: variant?.accent1 || 'var(--accent-1)' }} />
                        </span>
                      </button>
                    );
                  })}
                </div>

                <div style={{ marginTop: 16 }}>
                  <label className="login-label" htmlFor="oobe-font-family">
                    Font Family
                  </label>
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
                      <option key={fontOption.id} value={fontOption.id}>
                        {fontOption.label}
                      </option>
                    ))}
                  </select>
                </div>

                <div style={{ marginTop: 12 }}>
                  <label className="login-label" htmlFor="oobe-font-size-options">
                    Font Size
                  </label>
                  <div
                    id="oobe-font-size-options"
                    style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}
                  >
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
                  <button type="button" className="btn btn-secondary" onClick={goBack}>
                    Back
                  </button>
                  <button type="button" className="btn btn-primary" onClick={goNext}>
                    Next
                  </button>
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

                <div style={{ margin: '16px 0 12px' }}>
                  <label className="login-label" htmlFor="oobe-language">
                    Preferred Language
                  </label>
                  <select
                    id="oobe-language"
                    className="form-control"
                    value={language}
                    onChange={(e) => setLanguage(e.target.value)}
                  >
                    {languages.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
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
            )}

            {step === 5 && (
              <>
                <h2 className="login-card-title">Email Recovery Setup</h2>
                <p className="login-card-subtitle">
                  Recommended: configure SMTP now so Circuit Breaker can send password reset emails
                  and user invites. Set your external app URL too so those links work outside your
                  local network. You can skip SMTP and rely on your vault key as the offline
                  recovery path.
                </p>

                {/* ── Caddy HTTPS notice ── */}
                {_caddyDetection.active && (
                  <div
                    style={{
                      background: 'color-mix(in srgb, var(--color-primary) 8%, transparent)',
                      border: '1px solid color-mix(in srgb, var(--color-primary) 25%, transparent)',
                      borderRadius: 6,
                      padding: '10px 14px',
                      marginBottom: 18,
                      fontSize: '0.82rem',
                      lineHeight: 1.6,
                    }}
                  >
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 7,
                        marginBottom: 6,
                        fontWeight: 600,
                      }}
                    >
                      <Lock size={13} style={{ color: 'var(--color-primary)', flexShrink: 0 }} />
                      {_caddyDetection.isHttps
                        ? 'Caddy HTTPS is active'
                        : 'Caddy HTTPS is available'}
                    </div>
                    {!_caddyDetection.isHttps && (
                      <p style={{ margin: '0 0 6px' }}>
                        Caddy is running and will upgrade your connection to HTTPS. Install the CA
                        certificate so your browser trusts it without warnings.
                      </p>
                    )}
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 4 }}>
                      <a
                        href={_caddyDetection.certUrl}
                        download="caddy-root-ca.crt"
                        className="btn btn-secondary btn-sm"
                        style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}
                      >
                        <Download size={12} />
                        Download CA Certificate
                      </a>
                      {!_caddyDetection.isHttps && (
                        <a
                          href={_caddyDetection.httpsOrigin}
                          target="_blank"
                          rel="noreferrer"
                          className="btn btn-secondary btn-sm"
                          style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}
                        >
                          <ExternalLink size={12} />
                          Open HTTPS URL
                        </a>
                      )}
                    </div>
                    <p
                      style={{
                        margin: '8px 0 0',
                        fontSize: '0.75rem',
                        color: 'var(--color-text-muted)',
                      }}
                    >
                      Install the certificate in your OS or browser trust store. On macOS:
                      double-click and set to <em>Always Trust</em>. On Windows: import into{' '}
                      <em>Trusted Root Certification Authorities</em>. On Linux:{' '}
                      <code>
                        sudo cp caddy-root-ca.crt /usr/local/share/ca-certificates/ && sudo
                        update-ca-certificates
                      </code>
                      .
                    </p>
                  </div>
                )}

                <div style={{ marginBottom: 18 }}>
                  <label className="login-label" htmlFor="oobe-external-app-url">
                    External App URL <span style={{ opacity: 0.7 }}>(optional)</span>
                  </label>
                  <input
                    id="oobe-external-app-url"
                    className="login-input"
                    value={externalAppUrl}
                    onChange={(event) => {
                      setExternalAppUrl(event.target.value);
                      setError('');
                    }}
                    placeholder="https://cb.example.com"
                    autoComplete="url"
                  />
                  <p
                    style={{
                      fontSize: '0.75rem',
                      color: 'var(--color-text-muted)',
                      margin: '6px 0 0',
                      lineHeight: 1.5,
                    }}
                  >
                    Used in password reset and invite emails so remote users open the public Circuit
                    Breaker URL instead of a local address.
                  </p>
                </div>

                <label
                  style={{
                    display: 'flex',
                    alignItems: 'flex-start',
                    gap: 10,
                    cursor: 'pointer',
                    marginBottom: 18,
                  }}
                >
                  <input
                    type="checkbox"
                    checked={smtpEnabled}
                    onChange={(event) => {
                      setSmtpEnabled(event.target.checked);
                      setError('');
                    }}
                    style={{
                      marginTop: 2,
                      accentColor: 'var(--color-primary)',
                      width: 16,
                      height: 16,
                      flexShrink: 0,
                    }}
                  />
                  <span style={{ fontSize: '0.85rem' }}>
                    Configure SMTP now for password reset emails and invite delivery.
                  </span>
                </label>

                <div
                  style={{
                    display: 'grid',
                    gap: 14,
                    opacity: smtpEnabled ? 1 : 0.65,
                  }}
                >
                  <div>
                    <label className="login-label" htmlFor="oobe-smtp-host">
                      SMTP Host
                    </label>
                    <input
                      id="oobe-smtp-host"
                      className="login-input"
                      value={smtpHost}
                      onChange={(event) => {
                        setSmtpHost(event.target.value);
                        setError('');
                      }}
                      placeholder="smtp.example.com"
                      disabled={!smtpEnabled}
                    />
                  </div>

                  <div
                    style={{
                      display: 'grid',
                      gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
                      gap: 12,
                    }}
                  >
                    <div>
                      <label className="login-label" htmlFor="oobe-smtp-port">
                        SMTP Port
                      </label>
                      <input
                        id="oobe-smtp-port"
                        className="login-input"
                        value={smtpPort}
                        onChange={(event) => {
                          setSmtpPort(event.target.value);
                          setError('');
                        }}
                        inputMode="numeric"
                        placeholder="587"
                        disabled={!smtpEnabled}
                      />
                    </div>
                    <div>
                      <label className="login-label" htmlFor="oobe-smtp-from-name">
                        From Name
                      </label>
                      <input
                        id="oobe-smtp-from-name"
                        className="login-input"
                        value={smtpFromName}
                        onChange={(event) => setSmtpFromName(event.target.value)}
                        placeholder="Circuit Breaker"
                        disabled={!smtpEnabled}
                      />
                    </div>
                  </div>

                  <div>
                    <label className="login-label" htmlFor="oobe-smtp-from-email">
                      From Email
                    </label>
                    <input
                      id="oobe-smtp-from-email"
                      className="login-input"
                      type="email"
                      value={smtpFromEmail}
                      onChange={(event) => {
                        setSmtpFromEmail(event.target.value);
                        setError('');
                      }}
                      placeholder="noreply@example.com"
                      disabled={!smtpEnabled}
                    />
                  </div>

                  <div>
                    <label className="login-label" htmlFor="oobe-smtp-username">
                      SMTP Username <span style={{ opacity: 0.7 }}>(optional)</span>
                    </label>
                    <input
                      id="oobe-smtp-username"
                      className="login-input"
                      value={smtpUsername}
                      onChange={(event) => setSmtpUsername(event.target.value)}
                      placeholder="SMTP account username"
                      disabled={!smtpEnabled}
                    />
                  </div>

                  <div>
                    <label className="login-label" htmlFor="oobe-smtp-password">
                      SMTP Password <span style={{ opacity: 0.7 }}>(optional)</span>
                    </label>
                    <input
                      id="oobe-smtp-password"
                      className="login-input"
                      type="password"
                      value={smtpPassword}
                      onChange={(event) => setSmtpPassword(event.target.value)}
                      placeholder="Leave blank if your mail server does not require auth"
                      disabled={!smtpEnabled}
                    />
                  </div>

                  <label
                    style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.85rem' }}
                  >
                    <input
                      type="checkbox"
                      checked={smtpTls}
                      onChange={(event) => setSmtpTls(event.target.checked)}
                      disabled={!smtpEnabled}
                      style={{ accentColor: 'var(--color-primary)', width: 16, height: 16 }}
                    />
                    Use TLS / STARTTLS when connecting
                  </label>
                </div>

                <p
                  style={{
                    fontSize: '0.75rem',
                    color: 'var(--color-text-muted)',
                    margin: '12px 0 0',
                    lineHeight: 1.6,
                  }}
                >
                  SMTP gives users a convenient email reset flow. Your vault key is still the
                  offline recovery mechanism if email delivery is unavailable.
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
            )}

            {step === 6 && (
              <>
                <h2 className="login-card-title">Confirmation</h2>
                <p className="login-card-subtitle">Review and complete setup.</p>

                <div className="oobe-summary">
                  <img
                    src={sanitizeImageSrc(photoPreview || gravatarPreview)}
                    alt="Avatar preview"
                    className="oobe-avatar"
                  />
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
                      {FONT_OPTIONS.find((entry) => entry.id === selectedFont)?.label ??
                        selectedFont}{' '}
                      ·{' '}
                      {FONT_SIZE_OPTIONS.find((entry) => entry.id === selectedFontSize)?.label ??
                        selectedFontSize}
                    </div>
                    <div>
                      <strong>Language:</strong>{' '}
                      {languages.find((entry) => entry.value === language)?.label ?? language}
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

                <div className="oobe-actions">
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={goBack}
                    disabled={submitting}
                  >
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
            )}

            {error && (
              <div className="login-error-banner" role="alert">
                {error}
              </div>
            )}
          </div>

          {/* Desktop / tablet hint — 3rd column, hidden on mobile */}
          {step === 2 && <div className="oobe-hint-desktop-wrap">{avatarHintCard}</div>}
          {step === 3 && <div className="oobe-hint-desktop-wrap">{themeHintCard}</div>}
          {step === 4 && <div className="oobe-hint-desktop-wrap">{regionalHintCard}</div>}
        </div>
        {/* end oobe-step3-row */}
      </div>
    </div>
  );
}

OOBEWizardPage.propTypes = {
  onCompleted: PropTypes.func,
};

export default OOBEWizardPage;
