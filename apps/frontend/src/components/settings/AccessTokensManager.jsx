import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Download, EyeOff, KeyRound, Search } from 'lucide-react';
import {
  createServiceAccount,
  createToken,
  getScopeCatalog,
  listTokens,
  revokeToken,
  rotateToken,
} from '../../api/tokens';
import {
  confirmPhraseForToken,
  derivePosture,
  displayTokenLabel,
  downloadTextFile,
  filterTokens,
  issuanceRisk,
  tokensToCsv,
  tokensToJson,
} from '../../lib/accessTokens';
import EmptyState from '../common/EmptyState';
import HighRiskConfirmDialog from '../common/HighRiskConfirmDialog';
import Panel from '../common/Panel';
import { useToast } from '../common/Toast';
import OneTimeSecretModal from './OneTimeSecretModal';
import '../../styles/access-tokens.css';

const EXPIRY_OPTIONS = [
  { label: '90 days', days: 90 },
  { label: '1 year', days: 365 },
  { label: 'Never', days: null },
];

function expiryToIso(days) {
  if (days == null) return null;
  return new Date(Date.now() + days * 86400000).toISOString();
}

function formatWhen(iso) {
  if (!iso) return 'never';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? 'never' : d.toLocaleDateString();
}

function riskBadgeClass(level) {
  if (level === 'high' || level === 'elevated') return 'access-tokens__badge--warn';
  return 'access-tokens__badge--ok';
}

function AccessTokensManager() {
  const toast = useToast();
  const issueRef = useRef(null);
  const labelRef = useRef(null);

  // Admin workbench defaults to fleet inventory (plan 09).
  const [scope, setScope] = useState('all');
  const [tokens, setTokens] = useState([]);
  const [catalog, setCatalog] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [query, setQuery] = useState('');
  const [typeFilter, setTypeFilter] = useState('all');

  const [label, setLabel] = useState('');
  const [expiryDays, setExpiryDays] = useState(90);
  const [presetKey, setPresetKey] = useState(null);
  const [asServiceAccount, setAsServiceAccount] = useState(false);
  const [creating, setCreating] = useState(false);

  const [revealed, setRevealed] = useState(null);
  const [confirm, setConfirm] = useState(null);
  const [busy, setBusy] = useState(false);
  const [confirmError, setConfirmError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [list, cat] = await Promise.all([listTokens(scope), getScopeCatalog()]);
      setTokens(list.data || []);
      setCatalog(cat.data);
      setPresetKey((current) => current ?? cat.data?.presets?.[0]?.key ?? null);
    } catch (err) {
      setError(err?.userMessage || 'Could not load API tokens.');
    } finally {
      setLoading(false);
    }
  }, [scope]);

  useEffect(() => {
    load();
  }, [load]);

  const presets = useMemo(() => catalog?.presets || [], [catalog]);
  const selectedPreset = useMemo(
    () => presets.find((p) => p.key === presetKey) || presets[0],
    [presets, presetKey]
  );

  const visibleTokens = useMemo(
    () => filterTokens(tokens, { query, typeFilter }),
    [tokens, query, typeFilter]
  );
  const posture = useMemo(() => derivePosture(tokens), [tokens]);
  const risk = useMemo(
    () => issuanceRisk({ scopes: selectedPreset?.scopes || [], expiryDays }),
    [selectedPreset, expiryDays]
  );

  const handleCreate = useCallback(async () => {
    if (!selectedPreset) return;
    setCreating(true);
    try {
      const payload = {
        label: label.trim() || null,
        expires_at: expiryToIso(expiryDays),
        scopes: selectedPreset.scopes,
      };
      const fn = asServiceAccount ? createServiceAccount : createToken;
      const res = await fn(payload);
      setRevealed(res.data);
      setLabel('');
      toast.success('Token created.');
      await load();
    } catch (err) {
      toast.error(err?.userMessage || 'Could not create the token.');
    } finally {
      setCreating(false);
    }
  }, [selectedPreset, label, expiryDays, asServiceAccount, toast, load]);

  const handleConfirmed = useCallback(async () => {
    if (!confirm) return;
    setBusy(true);
    setConfirmError(null);
    try {
      if (confirm.mode === 'revoke') {
        await revokeToken(confirm.token.id);
        toast.success('Token revoked.');
      } else {
        const res = await rotateToken(confirm.token.id);
        setRevealed(res.data);
        toast.success('Token rotated. The previous secret no longer works.');
      }
      setConfirm(null);
      await load();
    } catch (err) {
      setConfirmError(err?.userMessage || 'Operation failed.');
    } finally {
      setBusy(false);
    }
  }, [confirm, toast, load]);

  const handleCopySecret = useCallback(async () => {
    if (!revealed?.token) return;
    try {
      if (!navigator.clipboard?.writeText) {
        throw new Error('Clipboard unavailable');
      }
      await navigator.clipboard.writeText(revealed.token);
      toast.success('Secret copied.');
    } catch {
      toast.error('Could not copy to the clipboard. Select the secret and copy it manually.');
    }
  }, [revealed, toast]);

  const handleExport = useCallback(
    (format) => {
      const stamp = new Date().toISOString().slice(0, 10);
      if (format === 'json') {
        downloadTextFile(
          `circuitbreaker-access-tokens-${stamp}.json`,
          tokensToJson(visibleTokens),
          'application/json'
        );
      } else {
        downloadTextFile(
          `circuitbreaker-access-tokens-${stamp}.csv`,
          tokensToCsv(visibleTokens),
          'text/csv'
        );
      }
      toast.success('Exported metadata only — secrets are never included.');
    },
    [visibleTokens, toast]
  );

  if (loading) {
    return (
      <div className="access-tokens" aria-busy="true">
        <p>Loading credentials…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="access-tokens" role="alert">
        <p>{error}</p>
        <button type="button" className="btn btn-sm" onClick={load}>
          Retry
        </button>
      </div>
    );
  }

  const inventorySummary = scope === 'all' ? 'Fleet inventory' : 'Your credentials only';
  const postureScopeHint = scope === 'all' ? 'Across the install' : 'Among your tokens';

  return (
    <div className="access-tokens">
      <section className="access-tokens__posture" aria-label="Token posture">
        <div className="access-tokens__posture-cell">
          <div className="access-tokens__posture-label">
            <span>Active credentials</span>
            <KeyRound size={14} aria-hidden="true" />
          </div>
          <div className="access-tokens__posture-value">{posture.active}</div>
          <div className="access-tokens__posture-hint" data-tone="ok">
            Not expired · {postureScopeHint}
          </div>
        </div>
        <div className="access-tokens__posture-cell">
          <div className="access-tokens__posture-label">
            <span>Service accounts</span>
          </div>
          <div className="access-tokens__posture-value">{posture.serviceAccounts}</div>
          <div className="access-tokens__posture-hint">
            {tokens.length
              ? `${Math.round((posture.serviceAccounts / tokens.length) * 100)}% of inventory`
              : 'No credentials yet'}
          </div>
        </div>
        <div className="access-tokens__posture-cell">
          <div className="access-tokens__posture-label">
            <span>Expiring soon</span>
          </div>
          <div className="access-tokens__posture-value">{posture.expiringSoon}</div>
          <div
            className="access-tokens__posture-hint"
            data-tone={posture.expiringSoon > 0 ? 'warn' : undefined}
          >
            Within 14 days
          </div>
        </div>
        <div className="access-tokens__posture-cell">
          <div className="access-tokens__posture-label">
            <span>Privileged</span>
          </div>
          <div className="access-tokens__posture-value">{posture.privileged}</div>
          <div className="access-tokens__posture-hint">*:* or admin:*</div>
        </div>
      </section>

      <div className="access-tokens__layout">
        <Panel
          title="Credential inventory"
          summary={inventorySummary}
          bodyless
          actions={
            <div className="access-tokens__row-actions">
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => handleExport('csv')}
                disabled={visibleTokens.length === 0}
              >
                <Download size={14} aria-hidden="true" />
                Export CSV
              </button>
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => handleExport('json')}
                disabled={visibleTokens.length === 0}
              >
                Export JSON
              </button>
            </div>
          }
        >
          <div className="access-tokens__toolbar">
            <div className="access-tokens__scope-tabs" role="group" aria-label="Inventory">
              <button type="button" aria-pressed={scope === 'all'} onClick={() => setScope('all')}>
                All tokens <span className="mono">{scope === 'all' ? tokens.length : ''}</span>
              </button>
              <button
                type="button"
                aria-pressed={scope === 'mine'}
                onClick={() => setScope('mine')}
              >
                My tokens
              </button>
            </div>
            <div className="access-tokens__search">
              <Search className="access-tokens__search-icon" size={14} aria-hidden="true" />
              <input
                id="token-search"
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search label, owner, or scope"
                aria-label="Search credentials"
              />
            </div>
            <select
              className="access-tokens__type-filter"
              aria-label="Token type"
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
            >
              <option value="all">All types</option>
              <option value="user">User token</option>
              <option value="service">Service account</option>
            </select>
          </div>

          {visibleTokens.length === 0 ? (
            <EmptyState
              message={
                tokens.length === 0 ? 'No access tokens yet' : 'No credentials match this search'
              }
              hint={
                tokens.length === 0
                  ? 'Issue a credential from the panel on the right. Secrets are shown once.'
                  : 'Clear the search or widen the type filter.'
              }
            />
          ) : (
            <div className="access-tokens__table-wrap">
              <table className="access-tokens__table">
                <thead>
                  <tr>
                    <th>Credential</th>
                    <th>Type</th>
                    <th>Access</th>
                    <th>Owner</th>
                    <th>Expires</th>
                    <th>Last used</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {visibleTokens.map((t) => {
                    const name = displayTokenLabel(t);
                    return (
                      <tr key={t.id} data-testid={`token-row-${t.id}`}>
                        <td>
                          <strong>{name}</strong>
                        </td>
                        <td>
                          <span
                            className={`access-tokens__badge ${
                              t.is_service_account
                                ? 'access-tokens__badge--info'
                                : 'access-tokens__badge--ok'
                            }`}
                          >
                            {t.is_service_account ? 'service account' : 'user token'}
                          </span>
                        </td>
                        <td>
                          {t.scopes && t.scopes.length > 0 ? (
                            t.scopes.map((s) => (
                              <span key={s} className="access-tokens__chip">
                                {s}
                              </span>
                            ))
                          ) : (
                            <span className="access-tokens__chip">inherits creator</span>
                          )}
                        </td>
                        <td>{t.created_by_name || '—'}</td>
                        <td>{formatWhen(t.expires_at)}</td>
                        <td>{t.last_used_at ? formatWhen(t.last_used_at) : 'never'}</td>
                        <td>
                          <div className="access-tokens__row-actions">
                            <button
                              type="button"
                              className="btn btn-sm"
                              onClick={() => {
                                setConfirmError(null);
                                setConfirm({ mode: 'rotate', token: t });
                              }}
                            >
                              Rotate {name}
                            </button>
                            <button
                              type="button"
                              className="btn btn-sm btn-danger"
                              onClick={() => {
                                setConfirmError(null);
                                setConfirm({ mode: 'revoke', token: t });
                              }}
                            >
                              Revoke {name}
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          <div className="access-tokens__foot">
            <span>
              Showing {visibleTokens.length} of {tokens.length} credentials
            </span>
            <span>Secrets are never displayed after issuance</span>
          </div>
        </Panel>

        <div ref={issueRef} id="create-panel" className="access-tokens__issue">
          <Panel title="Issue credential" summary="Least privilege by default">
            <div className="access-tokens__issue-form">
              <div className="access-tokens__field">
                <label htmlFor="token-label">Credential label</label>
                <input
                  ref={labelRef}
                  id="token-label"
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                  placeholder="e.g. proxmox-exporter"
                />
              </div>

              <div className="access-tokens__issue-grid">
                <div className="access-tokens__field">
                  <label htmlFor="token-identity">Identity</label>
                  <select
                    id="token-identity"
                    value={asServiceAccount ? 'service' : 'user'}
                    onChange={(e) => setAsServiceAccount(e.target.value === 'service')}
                  >
                    <option value="user">User token</option>
                    <option value="service">Service account</option>
                  </select>
                </div>
                <div className="access-tokens__field">
                  <label htmlFor="token-expiry">Expires</label>
                  <select
                    id="token-expiry"
                    value={String(expiryDays)}
                    onChange={(e) =>
                      setExpiryDays(e.target.value === 'null' ? null : Number(e.target.value))
                    }
                  >
                    {EXPIRY_OPTIONS.map((o) => (
                      <option key={o.label} value={String(o.days)}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <fieldset>
                <legend>Access profile</legend>
                <div className="access-tokens__presets" role="radiogroup" aria-label="Access level">
                  {presets.map((p) => (
                    <label key={p.key} className="access-tokens__preset">
                      <input
                        type="radio"
                        name="token-preset"
                        value={p.key}
                        checked={presetKey === p.key}
                        onChange={() => setPresetKey(p.key)}
                        aria-label={p.label}
                      />
                      <strong aria-hidden="true">{p.label}</strong>
                      <span>
                        {p.description} ({p.scopes.join(', ')})
                      </span>
                    </label>
                  ))}
                </div>
              </fieldset>

              <div className="access-tokens__scope-preview">
                <div className="access-tokens__scope-preview-head">
                  <span>Effective scopes</span>
                  <span className={`access-tokens__badge ${riskBadgeClass(risk.level)}`}>
                    {risk.label}
                  </span>
                </div>
                <div>
                  {(selectedPreset?.scopes || []).map((s) => (
                    <span key={s} className="access-tokens__chip">
                      {s}
                    </span>
                  ))}
                </div>
              </div>

              <div className="access-tokens__risk-note">
                <EyeOff size={14} aria-hidden="true" />
                <span>{risk.hint}</span>
              </div>

              <div className="access-tokens__issue-foot">
                <span>Audit event recorded on create</span>
                <button
                  type="button"
                  className="access-tokens__create-btn"
                  disabled={creating || !selectedPreset}
                  onClick={handleCreate}
                >
                  <KeyRound size={14} aria-hidden="true" />
                  {creating ? 'Creating…' : 'Create token'}
                </button>
              </div>
            </div>
          </Panel>
        </div>
      </div>

      <OneTimeSecretModal
        open={revealed != null}
        secret={revealed?.token}
        title="Store this secret now"
        onAcknowledge={() => setRevealed(null)}
        onCopy={handleCopySecret}
      />

      <HighRiskConfirmDialog
        open={confirm != null}
        title={confirm?.mode === 'rotate' ? 'Rotate this token' : 'Revoke this token'}
        body={
          confirm?.mode === 'rotate' ? (
            <p>
              A new secret is issued and shown once. The current secret stops working immediately —
              anything still using it will start failing until it is updated. Rotation keeps the
              label, scopes, and expiry; the rotating admin becomes the recorded creator of the
              replacement row.
            </p>
          ) : (
            <p>
              The token stops working immediately and cannot be restored. Anything using it will
              start failing.
            </p>
          )
        }
        confirmPhrase={
          confirm ? confirmPhraseForToken(confirm.token, confirm.mode) : CONFIRM_PLACEHOLDER
        }
        busy={busy}
        error={confirmError}
        onConfirm={handleConfirmed}
        onCancel={() => setConfirm(null)}
      />
    </div>
  );
}

// Non-empty placeholder so HighRiskConfirmDialog never arms on ''.
const CONFIRM_PLACEHOLDER = 'CONFIRM';

export default AccessTokensManager;
