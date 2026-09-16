import React from 'react';
import { ChevronRight, Shield } from 'lucide-react';
import AccessTokensManager from '../components/settings/AccessTokensManager';
import '../styles/access-tokens.css';

/**
 * Admin credential operations workbench (INC-14 + plan 09).
 *
 * AccessTokensManager owns inventory/issuance state. This shell supplies the
 * page chrome from the approved SOC composition without duplicating API logic.
 * Create lives only in the Issue credential panel — no duplicate header CTA.
 */
export default function AccessTokensPage() {
  return (
    <div className="page access-tokens-page">
      <nav className="access-tokens-page__crumb" aria-label="Breadcrumb">
        <Shield size={12} aria-hidden="true" />
        <span>Administration</span>
        <ChevronRight size={12} aria-hidden="true" />
        <span>Access tokens</span>
      </nav>

      <div className="access-tokens-page__head">
        <div>
          <p className="access-tokens-page__eyebrow">
            Identity &amp; access / Credential operations
          </p>
          <h2>Access Tokens</h2>
          <p className="access-tokens-page__lead">
            Issue, audit, rotate, and revoke machine credentials across every administrator. Secrets
            are shown once; least privilege is chosen here — Profile still mints a personal
            credential with your own scopes.
          </p>
        </div>
      </div>

      <AccessTokensManager />
    </div>
  );
}
