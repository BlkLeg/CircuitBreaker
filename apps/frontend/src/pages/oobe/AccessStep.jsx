import React from 'react';
import { Download, ExternalLink, Lock } from 'lucide-react';
import { useOOBE } from './OOBEContext';

/**
 * Step 6 — external URL, TLS posture and the optional SMTP relay.
 *
 * Reads the wizard context rather than taking props; see `OOBEContext`
 * for why.
 */
export default function AccessStep() {
  const {
    _caddyDetection,
    externalAppUrl,
    goBack,
    goNext,
    openCertificateDownload,
    setError,
    setExternalAppUrl,
    setSmtpEnabled,
    setSmtpFromEmail,
    setSmtpFromName,
    setSmtpHost,
    setSmtpPassword,
    setSmtpPort,
    setSmtpTls,
    setSmtpUsername,
    smtpEnabled,
    smtpFromEmail,
    smtpFromName,
    smtpHost,
    smtpPassword,
    smtpPort,
    smtpTls,
    smtpUsername,
  } = useOOBE();

  return (
    <>
      <h2 className="login-card-title">Email Delivery Setup</h2>
      <p className="login-card-subtitle">
        Recommended: configure SMTP now so Circuit Breaker can send invites and outbound
        notifications. Set your external app URL so invite links work outside your local network.
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
            {_caddyDetection.isHttps ? 'Caddy HTTPS is active' : 'Caddy HTTPS is available'}
          </div>
          {!_caddyDetection.isHttps && (
            <p style={{ margin: '0 0 6px' }}>
              Caddy is running and will upgrade your connection to HTTPS. Install the CA certificate
              so your browser trusts it without warnings.
            </p>
          )}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 4 }}>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}
              onClick={openCertificateDownload}
            >
              <Download size={12} />
              Download CA Certificate
            </button>
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
            Install the certificate in your OS or browser trust store. On macOS: double-click and
            set to <em>Always Trust</em>. On Windows: import into{' '}
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
          Used in invite emails so remote users open the public Circuit Breaker URL instead of a
          local address.
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
          Configure SMTP now for invite delivery and outbound notifications.
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

        <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.85rem' }}>
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
        SMTP handles outbound emails. Vault key recovery remains the account reset path.
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
