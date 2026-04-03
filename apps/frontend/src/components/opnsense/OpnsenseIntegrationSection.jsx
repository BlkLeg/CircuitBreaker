import React, { useState, useEffect } from 'react';
import { useSettings } from '../../context/SettingsContext';
import { useToast } from '../common/Toast';
import { settingsApi } from '../../api/client.jsx';

function Toggle({ value, onChange }) {
  return (
    <button
      type="button"
      onClick={() => onChange(!value)}
      style={{
        flexShrink: 0,
        width: 40,
        height: 22,
        borderRadius: 999,
        border: 'none',
        cursor: 'pointer',
        background: value ? 'var(--color-primary)' : 'var(--color-border)',
        transition: 'background 0.2s',
      }}
    />
  );
}

export default function OpnsenseIntegrationSection() {
  const { settings, reloadSettings } = useSettings();
  const toast = useToast();

  const [expanded, setExpanded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);

  const [form, setForm] = useState({
    opnsense_enabled: false,
    opnsense_host: '',
    opnsense_verify_ssl: false,
  });
  const [creds, setCreds] = useState({ key: '', secret: '' });

  useEffect(() => {
    if (!settings) return;
    setForm({
      opnsense_enabled: settings.opnsense_enabled ?? false,
      opnsense_host: settings.opnsense_host ?? '',
      opnsense_verify_ssl: settings.opnsense_verify_ssl ?? false,
    });
  }, [settings]);

  const set = (k, v) => setForm((prev) => ({ ...prev, [k]: v }));
  const credentialsSet = settings?.opnsense_credentials_set ?? false;

  const handleSave = async () => {
    setSaving(true);
    try {
      const payload = {
        opnsense_enabled: form.opnsense_enabled,
        opnsense_host: form.opnsense_host,
        opnsense_verify_ssl: form.opnsense_verify_ssl,
      };
      if (creds.key) payload.opnsense_api_key = creds.key;
      if (creds.secret) payload.opnsense_api_secret = creds.secret;
      await settingsApi.update(payload);
      setCreds({ key: '', secret: '' });
      await reloadSettings();
      toast.success('OPNsense settings saved');
    } catch {
      toast.error('Failed to save OPNsense settings');
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const res = await settingsApi.opnsenseTest();
      setTestResult(res.data);
    } catch {
      setTestResult({ ok: false, error: 'Request failed' });
    } finally {
      setTesting(false);
    }
  };

  return (
    <div
      style={{
        border: '1px solid var(--color-border)',
        borderRadius: 8,
        overflow: 'hidden',
        marginBottom: 12,
      }}
    >
      {/* Header */}
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        style={{
          width: '100%',
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          padding: '12px 16px',
          background: 'var(--color-surface)',
          border: 'none',
          cursor: 'pointer',
          textAlign: 'left',
        }}
      >
        <img src="/icons/vendors/opnsense.png" alt="OPNsense" style={{ width: 22, height: 22 }} />
        <span style={{ fontSize: 14, fontWeight: 600, flex: 1 }}>OPNsense</span>
        {credentialsSet && <span style={{ fontSize: 11, color: '#22c55e' }}>✓ configured</span>}
        <span style={{ fontSize: 12, color: 'var(--color-text-muted)', marginLeft: 4 }}>
          {expanded ? '▲' : '▼'}
        </span>
      </button>

      {/* Body */}
      {expanded && (
        <div
          style={{
            padding: '16px',
            display: 'flex',
            flexDirection: 'column',
            gap: 14,
            background: 'var(--color-surface-alt)',
          }}
        >
          {/* Setup instructions — shown until credentials are saved */}
          {!credentialsSet && (
            <div
              style={{
                padding: '12px 14px',
                borderRadius: 6,
                background: 'rgba(251,191,36,0.07)',
                border: '1px solid rgba(251,191,36,0.25)',
                fontSize: 12,
              }}
            >
              <p style={{ margin: '0 0 8px', fontWeight: 600, fontSize: 13 }}>
                Getting your API credentials
              </p>
              <ol style={{ margin: 0, paddingLeft: 18, lineHeight: 1.9 }}>
                <li>
                  In OPNsense → <strong>System → Access → Users</strong> → add a new user
                </li>
                <li>
                  Under <strong>Privileges</strong>, add all of: <code>Diagnostics: ARP Table</code>
                  , <code>Services: DHCP: Kea(v4)</code> (OPNsense ≥ 24.1),{' '}
                  <code>Services: ISC DHCPv4</code> (older),{' '}
                  <code>Diagnostics: System Information</code>, <code>Diagnostics: CPU Usage</code>
                </li>
                <li>
                  Open the user → <strong>API Keys → Generate</strong> — download the{' '}
                  <code>.txt</code> file
                </li>
                <li>
                  Paste the <code>key=</code> and <code>secret=</code> values into the fields below
                </li>
              </ol>
            </div>
          )}

          {/* Enabled toggle */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div>
              <p style={{ margin: 0, fontSize: 13 }}>Enable OPNsense Integration</p>
              <p className="cb-hint">Use OPNsense as the authoritative discovery source</p>
            </div>
            <Toggle value={form.opnsense_enabled} onChange={(v) => set('opnsense_enabled', v)} />
          </div>

          {/* Host */}
          <div className="cb-field">
            <span className="cb-label">Host</span>
            <p className="cb-hint">IP address or hostname — HTTPS is used automatically</p>
            <input
              className="cb-input"
              type="text"
              value={form.opnsense_host}
              onChange={(e) => set('opnsense_host', e.target.value)}
              placeholder="192.168.1.1"
            />
          </div>

          {/* API Key */}
          <div className="cb-field">
            <span className="cb-label">
              API Key
              {credentialsSet && (
                <span style={{ marginLeft: 8, fontSize: 11, color: '#22c55e', fontWeight: 400 }}>
                  ✓ set
                </span>
              )}
            </span>
            <input
              className="cb-input"
              type="password"
              value={creds.key}
              onChange={(e) => setCreds((p) => ({ ...p, key: e.target.value }))}
              placeholder={credentialsSet ? '(stored — enter to replace)' : 'Paste API key'}
            />
          </div>

          {/* API Secret */}
          <div className="cb-field">
            <span className="cb-label">API Secret</span>
            <input
              className="cb-input"
              type="password"
              value={creds.secret}
              onChange={(e) => setCreds((p) => ({ ...p, secret: e.target.value }))}
              placeholder={credentialsSet ? '(stored — enter to replace)' : 'Paste API secret'}
            />
          </div>

          {/* Verify SSL */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div>
              <p style={{ margin: 0, fontSize: 13 }}>Verify SSL Certificate</p>
              <p className="cb-hint">Disable for self-signed certs (common in homelabs)</p>
            </div>
            <Toggle
              value={form.opnsense_verify_ssl}
              onChange={(v) => set('opnsense_verify_ssl', v)}
            />
          </div>

          {/* Actions */}
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <button
              type="button"
              onClick={handleSave}
              disabled={saving}
              style={{
                padding: '7px 18px',
                borderRadius: 6,
                border: 'none',
                cursor: saving ? 'not-allowed' : 'pointer',
                background: 'var(--color-primary)',
                color: '#fff',
                fontSize: 13,
                fontWeight: 500,
                opacity: saving ? 0.7 : 1,
              }}
            >
              {saving ? 'Saving…' : 'Save'}
            </button>
            <button
              type="button"
              onClick={handleTest}
              disabled={testing || !credentialsSet}
              style={{
                padding: '7px 18px',
                borderRadius: 6,
                border: '1px solid var(--color-border)',
                cursor: testing || !credentialsSet ? 'not-allowed' : 'pointer',
                background: 'var(--color-surface)',
                color: 'var(--color-text)',
                fontSize: 13,
                fontWeight: 500,
                opacity: testing || !credentialsSet ? 0.5 : 1,
              }}
            >
              {testing ? 'Testing…' : 'Test Connection'}
            </button>
          </div>

          {/* Test result */}
          {testResult && !testing && (
            <div
              style={{
                fontSize: 12,
                padding: '8px 12px',
                borderRadius: 6,
                background: testResult.ok ? 'rgba(34,197,94,0.08)' : 'rgba(239,68,68,0.08)',
                border: `1px solid ${testResult.ok ? 'rgba(34,197,94,0.2)' : 'rgba(239,68,68,0.2)'}`,
                color: testResult.ok ? '#22c55e' : '#ef4444',
                display: 'flex',
                flexDirection: 'column',
                gap: 4,
              }}
            >
              {testResult.ok ? (
                <>
                  <span style={{ fontWeight: 600 }}>Connected</span>
                  <span style={{ color: 'var(--color-text-muted)' }}>
                    {testResult.version && <span>v{testResult.version} · </span>}
                    {testResult.arp_count != null && (
                      <span>{testResult.arp_count} ARP entries · </span>
                    )}
                    {testResult.lease_count != null && <span>{testResult.lease_count} leases</span>}
                    {testResult.kea && <span> · Kea DHCP</span>}
                  </span>
                </>
              ) : (
                <span>Error: {testResult.error || 'Unknown error'}</span>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
