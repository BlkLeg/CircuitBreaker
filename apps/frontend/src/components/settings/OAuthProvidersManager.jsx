import React, { useState, useEffect, useCallback } from 'react';
import PropTypes from 'prop-types';
import api from '../../api/client';

const PROVIDERS = [
  { key: 'github', label: 'GitHub', icon: '🐙', type: 'oauth2' },
  { key: 'google', label: 'Google', icon: '🔵', type: 'oauth2' },
  { key: 'oidc', label: 'OIDC', icon: '🔑', type: 'oidc' },
];

function ProviderRow({ provKey, label, icon, type, config, onChange }) {
  const [expanded, setExpanded] = useState(false);
  const enabled = config?.enabled ?? false;

  const set = (key, val) => onChange(provKey, { ...config, [key]: val });

  return (
    <div style={{ borderBottom: '1px solid var(--color-border)', padding: '10px 0' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <label className="toggle-switch" style={{ marginTop: 0 }}>
          <span className="sr-only">Enable {label}</span>
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => set('enabled', e.target.checked)}
          />
          <span className="toggle-switch-track" />
        </label>
        <span style={{ fontSize: 13, fontWeight: 600 }}>
          {icon} {label}
        </span>
        <button
          className="btn btn-secondary btn-sm"
          onClick={() => setExpanded((v) => !v)}
          style={{ marginLeft: 'auto', padding: '2px 8px', fontSize: 12 }}
        >
          {expanded ? 'Hide' : 'Configure'}
        </button>
      </div>

      {expanded && (
        <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 8 }}>
          <input
            className="input-field"
            placeholder="Client ID"
            value={config?.client_id ?? ''}
            onChange={(e) => set('client_id', e.target.value)}
          />
          <input
            className="input-field"
            placeholder={
              config?.client_secret_set
                ? '(secret saved — enter new value to change)'
                : 'Client Secret'
            }
            type="password"
            autoComplete="new-password"
            onChange={(e) => set('client_secret', e.target.value)}
          />
          {type === 'oidc' && (
            <input
              className="input-field"
              placeholder="Discovery URL (e.g. https://auth.example.com/application/o/cb/.well-known/openid-configuration)"
              value={config?.discovery_url ?? ''}
              onChange={(e) => set('discovery_url', e.target.value)}
            />
          )}
          <p style={{ fontSize: 11, color: 'var(--color-text-muted)', margin: 0 }}>
            Redirect URI:{' '}
            <code style={{ userSelect: 'all' }}>
              {globalThis.location.origin}/api/v1/auth/oauth/
              {type === 'oidc' ? `oidc/${provKey}/callback` : `${provKey}/callback`}
            </code>
          </p>
        </div>
      )}
    </div>
  );
}

ProviderRow.propTypes = {
  provKey: PropTypes.string.isRequired,
  label: PropTypes.string.isRequired,
  icon: PropTypes.string.isRequired,
  type: PropTypes.string.isRequired,
  config: PropTypes.object,
  onChange: PropTypes.func.isRequired,
};

export default function OAuthProvidersManager() {
  const [oauthProviders, setOauthProviders] = useState({});
  const [oidcProviders, setOidcProviders] = useState([]);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      const res = await api.get('/settings/oauth');
      setOauthProviders(res.data?.oauth_providers ?? {});
      setOidcProviders(Array.isArray(res.data?.oidc_providers) ? res.data.oidc_providers : []);
    } catch {
      /* silent if not configured */
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleChange = (provKey, config) => {
    const provider = PROVIDERS.find((p) => p.key === provKey);
    if (provider?.type === 'oidc') {
      setOidcProviders((prev) => {
        const withoutCurrent = prev.filter((entry) => (entry.slug || entry.name) !== provKey);
        return [
          ...withoutCurrent,
          {
            ...config,
            slug: provKey,
            name: config?.name || provKey,
            label: config?.label || 'OIDC',
          },
        ];
      });
    } else {
      setOauthProviders((prev) => ({ ...prev, [provKey]: config }));
    }
    setSaved(false);
  };

  const getConfig = useCallback(
    (provider) => {
      if (provider.type === 'oidc') {
        return oidcProviders.find((entry) => (entry.slug || entry.name) === provider.key) || {};
      }
      return oauthProviders[provider.key] || {};
    },
    [oauthProviders, oidcProviders]
  );

  const handleSave = async () => {
    setSaving(true);
    setError('');
    setSaved(false);
    try {
      await api.patch('/settings/oauth', {
        oauth_providers: oauthProviders,
        oidc_providers: oidcProviders,
      });
      setSaved(true);
      load(); // reload to get masked secret state
    } catch (err) {
      setError(err?.response?.data?.detail || 'Failed to save OAuth settings.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ marginTop: '0.5rem' }}>
      {PROVIDERS.map(({ key, label, icon, type }) => (
        <ProviderRow
          key={key}
          provKey={key}
          label={label}
          icon={icon}
          type={type}
          config={getConfig({ key, type })}
          onChange={handleChange}
        />
      ))}

      {error && <div style={{ fontSize: 12, color: '#ef4444', marginTop: 8 }}>{error}</div>}
      {saved && (
        <div style={{ fontSize: 12, color: '#22c55e', marginTop: 8 }}>✓ OAuth settings saved.</div>
      )}

      <div style={{ marginTop: 12 }}>
        <button className="btn btn-primary btn-sm" onClick={handleSave} disabled={saving}>
          {saving ? 'Saving…' : 'Save OAuth Settings'}
        </button>
      </div>
    </div>
  );
}
