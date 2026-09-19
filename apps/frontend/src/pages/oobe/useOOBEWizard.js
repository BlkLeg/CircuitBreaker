/**
 * All of the first-run wizard's state, effects and transitions.
 *
 * `OOBEWizardPage` was 2,215 lines, of which the seven step bodies were about
 * 1,200 and this was most of the rest. The steps are components now; this is
 * the state they read, kept as a hook rather than left in the page so that the
 * page is what its name says — a layout that picks a step — and the wizard's
 * logic can be read, and changed, without scrolling past markup.
 *
 * Returns the shared `wizard` bag the steps consume through `OOBEContext`,
 * alongside the handful of values the page's own chrome needs: the step number,
 * the branding, and the post-bootstrap vault-key screen.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { authApi, OOBE_STEP_NAMES } from '../../api/auth.js';
import apiClient from '../../api/client';
import { useAuth } from '../../context/AuthContext.jsx';
import { useSettings } from '../../context/SettingsContext.jsx';
import { applyTheme } from '../../theme/applyTheme';
import { DEFAULT_PRESET, THEME_PRESETS } from '../../theme/presets';
import { FONT_OPTIONS, FONT_SIZE_OPTIONS } from '../../lib/fonts';
import { gravatarHash } from '../../utils/md5.js';
import { RULES, timezoneToCity } from './constants';

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export default function useOOBEWizard({ onCompleted }) {
  const navigate = useNavigate();
  const location = useLocation();
  const { login } = useAuth();
  const { settings, reloadSettings } = useSettings();
  const branding = settings?.branding;
  const airgapMode = settings?.airgapMode ?? settings?.airgap_mode ?? false;

  const [step, setStep] = useState(1);
  const [fqdn, setFqdn] = useState('');
  const [domainApplying, setDomainApplying] = useState(false);
  const [domainResult, setDomainResult] = useState(null); // { fqdn, app_url } on success
  const [domainError, setDomainError] = useState('');
  const [, setOnboardingLoaded] = useState(false);
  const [email, setEmail] = useState('');
  const [setupToken, setSetupToken] = useState('');
  // Where the operator can read the token. Resolved server-side because
  // CB_DATA_DIR differs per deployment; never the token itself.
  const [setupTokenPath, setSetupTokenPath] = useState(null);
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [selectedPreset, setSelectedPreset] = useState(DEFAULT_PRESET);
  const [selectedThemeMode, setSelectedThemeMode] = useState('dark');
  const [selectedFont, setSelectedFont] = useState(settings?.ui_font ?? 'inter');
  const [selectedFontSize, setSelectedFontSize] = useState(settings?.ui_font_size ?? 'medium');
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
  const [avatarLoadError, setAvatarLoadError] = useState(false);
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

  // Reset avatar error when email, photo, or step changes so Gravatar/photo can retry.
  useEffect(() => {
    setAvatarLoadError(false);
  }, [email, photoPreview, step]);

  useEffect(() => {
    let cancelled = false;
    authApi
      .bootstrapStatus()
      .then((res) => {
        if (!cancelled) setSetupTokenPath(res?.data?.setup_token_path || null);
      })
      .catch(() => {
        // A missing hint is a worse wizard, not a broken one — the token field
        // still works, so never let this block bootstrap.
        if (!cancelled) setSetupTokenPath(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

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

  const openCertificateDownload = useCallback(async () => {
    if (!_caddyDetection.active) return;
    try {
      const response = await fetch(_caddyDetection.certUrl);
      if (!response.ok) throw new Error('Failed to fetch certificate');
      const blob = await response.blob();

      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'circuitbreaker.crt';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Error downloading certificate:', err);
    }
  }, [_caddyDetection]);

  // Auto-populate external app URL when running behind Caddy and field is empty.
  useEffect(() => {
    if (step === 6 && !externalAppUrl && _caddyDetection.active) {
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

  // Load persisted onboarding step from backend (Homarr-style resume).
  useEffect(() => {
    authApi
      .getOnboardingStep()
      .then((res) => {
        const current = res.data?.current_step;
        if (current && OOBE_STEP_NAMES.includes(current)) {
          const num = OOBE_STEP_NAMES.indexOf(current) + 1;
          setStep(num);
        }
      })
      .catch((err) => {
        console.warn('Failed to fetch onboarding step:', err);
      })
      .finally(() => setOnboardingLoaded(true));
  }, []);

  // Force the default theme on mount so the OOBE always starts with the
  // correct visual regardless of what SettingsContext loaded from the API.
  useEffect(() => {
    document.documentElement.dataset.theme = selectedThemeMode;
    applyTheme(THEME_PRESETS[DEFAULT_PRESET], DEFAULT_PRESET);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // OAuth bootstrap return: /oobe?cb_auth_code=...&bootstrap=1&provider=...
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const authCode = params.get('cb_auth_code');
    const isBootstrap = params.get('bootstrap') === '1';
    if (!authCode || !isBootstrap) return;

    // Restore in-progress OOBE state saved before the OAuth redirect
    try {
      const saved = JSON.parse(sessionStorage.getItem('oobe_state') || '{}');
      if (saved.selectedPreset) setSelectedPreset(saved.selectedPreset);
      if (saved.selectedThemeMode) setSelectedThemeMode(saved.selectedThemeMode);
      if (saved.timezone) setTimezone(saved.timezone);
      if (saved.selectedFont) setSelectedFont(saved.selectedFont);
      if (saved.selectedFontSize) setSelectedFontSize(saved.selectedFontSize);
      if (saved.weatherLocation) setWeatherLocation(saved.weatherLocation);
      if (saved.externalAppUrl) setExternalAppUrl(saved.externalAppUrl);
      if (saved.setupToken) setSetupToken(saved.setupToken);
    } catch (err) {
      console.warn('OOBE state restore failed (defaults used):', err);
    }
    sessionStorage.removeItem('oobe_state');

    setOauthBootstrapProvider(params.get('provider') || 'oauth');

    authApi
      .exchangeAuthCode(authCode)
      .then((res) => {
        const token = res.data.token;
        setOauthBootstrapToken(token);
        return authApi.meWithToken(token);
      })
      .then((res) => {
        const user = res.data || {};
        setOauthBootstrapEmail(user.email || null);
        setEmail(user.email || '');
        if (user.display_name) {
          setDisplayName((current) => current || user.display_name);
        }
        if (user.profile_photo_url) {
          setPhotoPreview(user.profile_photo_url);
        }
      })
      .catch((err) => {
        console.error('OAuth bootstrap exchange or profile fetch failed in OOBE:', err);
      });

    // Clean code from URL without triggering a re-render loop
    globalThis.history.replaceState({}, '', '/oobe');
    // Skip account creation step — go straight to theme
    setStep(4);
    authApi.setOnboardingStep('theme').catch((err) => {
      console.warn('Failed to persist onboarding step (theme):', err);
    });
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

  const searchLocation = useCallback(
    async (query) => {
      const q = query.trim();
      if (q.length < 2) {
        setLocationResults([]);
        setLocationDropdownOpen(false);
        return;
      }
      // Same reason as HeaderWidgets: a third-party call the backend's air-gap
      // choke point cannot see. The operator types the location by hand rather
      // than having it sent away to be autocompleted.
      if (airgapMode) {
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
      } catch (err) {
        console.warn('OOBE location search failed:', err);
        setLocationResults([]);
      } finally {
        setLocationSearching(false);
      }
    },
    [airgapMode]
  );

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

  const setupTokenValid = setupToken.trim().length >= 16;
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

  const persistStep = (nextStepNum) => {
    const name = OOBE_STEP_NAMES[nextStepNum - 1];
    if (name) {
      authApi.setOnboardingStep(name).catch((err) => {
        console.warn('Failed to persist onboarding step:', err);
      });
    }
  };

  const goNext = () => {
    if (step === 3 && !setupTokenValid) {
      setError('Enter the setup token from your server before continuing.');
      return;
    }
    if (step === 3 && !oauthBootstrapToken && !accountValid) {
      setError('Please fix account validation errors before continuing.');
      return;
    }
    if (step === 6) {
      const smtpError = validateSmtpStep();
      if (smtpError) {
        setError(smtpError);
        return;
      }
    }
    setError('');
    const next = Math.min(7, step + 1);
    setStep(next);
    persistStep(next);
  };

  const goBack = () => {
    setError('');
    const prev = Math.max(1, step - 1);
    setStep(prev);
    persistStep(prev);
  };

  const goBackToStart = () => {
    setError('');
    setStep(1);
    persistStep(1);
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

    // Faces are self-hosted (styles/fonts.css); previewing a font is a pure
    // style change. Clears the <link> an earlier version of the app injected.
    document.getElementById('cb-font-link')?.remove();

    document.documentElement.style.setProperty('--font', font.stack);
    document.documentElement.style.setProperty('--font-size-base', `${size.rootPx}px`);
    document.documentElement.style.fontSize = `${size.rootPx}px`;
  };

  const submitDomain = async () => {
    setDomainApplying(true);
    setDomainError('');
    try {
      const resp = await authApi.bootstrapConfigureDomain(fqdn.trim());
      setDomainResult(resp.data ?? resp);
    } catch (err) {
      setDomainError(
        err?.response?.data?.detail ||
          'Could not apply that domain — staying on the IP address is safe. You can retry or skip.'
      );
    } finally {
      setDomainApplying(false);
    }
  };

  const skipDomain = () => {
    setDomainError('');
    goNext();
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
    } catch (err) {
      console.error('OOBE OAuth provider save failed:', err);
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
        selectedFont,
        selectedFontSize,
        weatherLocation,
        externalAppUrl,
        setupToken,
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
    if (!setupTokenValid) {
      setStep(3);
      setError('Enter the setup token from your server before finishing setup.');
      return;
    }
    if (localAccountRequired && !accountValid) {
      setStep(3);
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
          setup_token: setupToken.trim(),
          oauth_token: oauthBootstrapToken,
          display_name: displayName || undefined,
          ...sharedSettings,
        });
      } else {
        response = await authApi.bootstrapInitialize({
          setup_token: setupToken.trim(),
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
        } catch (err) {
          console.warn('OOBE profile photo upload failed (account created):', err);
        }
      }

      if (THEME_PRESETS[preset]) {
        applyTheme(THEME_PRESETS[preset], preset);
      }

      login(token, user);
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
    } catch (err) {
      console.warn('Clipboard write failed, user can manually select:', err);
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

  // Vault key ceremony overlay — shown after bootstrap when key is generated

  const wizard = {
    _caddyDetection,
    applyFontInstant,
    avatarLoadError,
    clearPhoto,
    confirmPassword,
    displayName,
    domainApplying,
    domainError,
    domainResult,
    email,
    externalAppUrl,
    fqdn,
    goBack,
    goNext,
    gravatarPreview,
    handleLocationQueryChange,
    handleOauthSignup,
    handlePhotoFile,
    handleTimezoneChange,
    locationDropdownOpen,
    locationDropdownRef,
    locationInputRef,
    locationQuery,
    locationResults,
    locationSearching,
    oauthBootstrapEmail,
    oauthBootstrapProvider,
    oauthBootstrapToken,
    oauthSetupClientId,
    oauthSetupClientSecret,
    oauthSetupDiscoveryUrl,
    oauthSetupMode,
    oauthSetupProvider,
    oauthSetupSaving,
    openCertificateDownload,
    password,
    passwordsMatch,
    photoFile,
    photoFileRef,
    photoPreview,
    selectLocationResult,
    selectMode,
    selectPreset,
    selectedFont,
    selectedFontSize,
    selectedPreset,
    selectedThemeMode,
    setAvatarLoadError,
    setConfirmPassword,
    setDisplayName,
    setDomainError,
    setEmail,
    setError,
    setExternalAppUrl,
    setFqdn,
    setLocationDropdownOpen,
    setLocationQuery,
    setLocationResults,
    setOauthBootstrapEmail,
    setOauthBootstrapProvider,
    setOauthBootstrapToken,
    setOauthSetupClientId,
    setOauthSetupClientSecret,
    setOauthSetupDiscoveryUrl,
    setOauthSetupMode,
    setOauthSetupProvider,
    setPassword,
    setSelectedFont,
    setSelectedFontSize,
    setSetupToken,
    setSmtpEnabled,
    setSmtpFromEmail,
    setSmtpFromName,
    setSmtpHost,
    setSmtpPassword,
    setSmtpPort,
    setSmtpTls,
    setSmtpUsername,
    setupToken,
    setupTokenPath,
    skipDomain,
    smtpEnabled,
    smtpFromEmail,
    smtpFromName,
    smtpHost,
    smtpPassword,
    smtpPort,
    smtpTls,
    smtpUsername,
    submitBootstrap,
    submitDomain,
    submitting,
    timezone,
    weatherLocation,
  };

  return {
    wizard,
    branding,
    error,
    goBackToStart,
    handleVaultKeyContinue,
    handleVaultKeyCopy,
    handleVaultKeyDownload,
    setVaultKeyAcked,
    step,
    vaultKey,
    vaultKeyAcked,
    vaultKeyCopied,
  };
}
