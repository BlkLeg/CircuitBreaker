import React from 'react';
import { useOOBE } from './OOBEContext';

/**
 * Step 2 — the optional public domain, and the DNS check behind it.
 *
 * Reads the wizard context rather than taking props; see `OOBEContext`
 * for why.
 */
export default function DomainStep() {
  const {
    domainApplying,
    domainError,
    domainResult,
    fqdn,
    setDomainError,
    setFqdn,
    skipDomain,
    submitDomain,
  } = useOOBE();

  return (
    <>
      <h2 className="login-card-title">Domain</h2>
      <p className="login-card-subtitle">
        Optional: set a domain name so Circuit Breaker gets a proper HTTPS certificate. You can
        always skip this and use the IP address.
      </p>

      {!domainResult && (
        <div style={{ marginBottom: 18 }}>
          <label className="login-label" htmlFor="oobe-fqdn">
            Domain (FQDN)
          </label>
          <input
            id="oobe-fqdn"
            type="text"
            className="login-input"
            placeholder="circuitbreaker.example.com"
            value={fqdn}
            onChange={(event) => {
              setFqdn(event.target.value);
              setDomainError('');
            }}
            disabled={domainApplying}
          />
          <p
            style={{
              fontSize: '0.75rem',
              color: 'var(--color-text-muted)',
              margin: '6px 0 0',
              lineHeight: 1.5,
            }}
          >
            We’ll generate a matching self-signed certificate and reconfigure nginx. IP-based access
            stays available as a fallback.
          </p>
        </div>
      )}

      {domainResult && (
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
          <div style={{ fontWeight: 600, marginBottom: 6 }}>Domain configured</div>
          <p style={{ margin: '0 0 8px' }}>
            Circuit Breaker is now reachable at <code>{domainResult.app_url}</code>.
          </p>
          <a href={domainResult.app_url} className="btn btn-primary">
            Continue at {domainResult.app_url}
          </a>
        </div>
      )}

      {!domainResult && (
        <div className="oobe-actions">
          <button
            type="button"
            className="btn btn-secondary"
            onClick={skipDomain}
            disabled={domainApplying}
          >
            Skip
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={submitDomain}
            disabled={domainApplying || !fqdn.trim()}
          >
            {domainApplying ? 'Applying…' : 'Apply'}
          </button>
        </div>
      )}

      {domainError && (
        <div className="login-error-banner" role="alert">
          {domainError}
        </div>
      )}
    </>
  );
}
