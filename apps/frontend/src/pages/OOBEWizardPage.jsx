import React from 'react';
import PropTypes from 'prop-types';
import { CheckCircle2, Copy, Download, ShieldAlert } from 'lucide-react';
import OOBEContext from './oobe/OOBEContext';
import useOOBEWizard from './oobe/useOOBEWizard';
import WelcomeStep from './oobe/WelcomeStep';
import DomainStep from './oobe/DomainStep';
import AccountStep from './oobe/AccountStep';
import ThemeStep from './oobe/ThemeStep';
import RegionalStep from './oobe/RegionalStep';
import AccessStep from './oobe/AccessStep';
import ReviewStep from './oobe/ReviewStep';
import RegionalHintCard from './oobe/RegionalHintCard';
import AvatarHintCard from './oobe/AvatarHintCard';
import ThemeHintCard from './oobe/ThemeHintCard';

function OOBEWizardPage({ onCompleted }) {
  const {
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
  } = useOOBEWizard({ onCompleted });

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
              <div className="oobe-progress">Step 8/8</div>

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
                now. This vault key is your account recovery fallback.
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

  // Everything the seven step components read. Assembled here rather than
  // memoised: the steps used to be part of this component's own render, so
  // they already re-rendered on every state change and a stable identity
  // would buy nothing.

  return (
    <OOBEContext.Provider value={wizard}>
      <div className="login-root">
        <div className="login-bokeh-tl" aria-hidden="true" />
        <div className="login-bokeh-br" aria-hidden="true" />
        <div
          className={`oobe-layout${step === 3 || step === 4 || step === 5 ? ' oobe-layout--theme-step' : ''}`}
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
          {step === 3 && (
            <div className="oobe-hint-mobile-wrap">
              <AvatarHintCard />
            </div>
          )}
          {step === 4 && (
            <div className="oobe-hint-mobile-wrap">
              <ThemeHintCard />
            </div>
          )}
          {step === 5 && (
            <div className="oobe-hint-mobile-wrap">
              <RegionalHintCard />
            </div>
          )}

          <div
            className={`oobe-step3-row${step === 3 || step === 4 || step === 5 ? ' oobe-step3-row--active' : ''}`}
          >
            <div className="login-card oobe-card">
              <div className="oobe-progress-row">
                <div className="oobe-progress">Step {step}/7</div>
                {step > 1 && (
                  <button type="button" className="oobe-back-to-start" onClick={goBackToStart}>
                    Back to start
                  </button>
                )}
              </div>

              {step === 1 && <WelcomeStep />}

              {step === 2 && <DomainStep />}

              {step === 3 && <AccountStep />}

              {step === 4 && <ThemeStep />}

              {step === 5 && <RegionalStep />}

              {step === 6 && <AccessStep />}

              {step === 7 && <ReviewStep />}

              {error && (
                <div className="login-error-banner" role="alert">
                  {error}
                </div>
              )}
            </div>

            {/* Desktop / tablet hint — 3rd column, hidden on mobile */}
            {step === 3 && (
              <div className="oobe-hint-desktop-wrap">
                <AvatarHintCard />
              </div>
            )}
            {step === 4 && (
              <div className="oobe-hint-desktop-wrap">
                <ThemeHintCard />
              </div>
            )}
            {step === 5 && (
              <div className="oobe-hint-desktop-wrap">
                <RegionalHintCard />
              </div>
            )}
          </div>
          {/* end oobe-step3-row */}
        </div>
      </div>
    </OOBEContext.Provider>
  );
}

OOBEWizardPage.propTypes = {
  onCompleted: PropTypes.func,
};

export default OOBEWizardPage;
