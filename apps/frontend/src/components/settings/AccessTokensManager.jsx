import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  createServiceAccount,
  createToken,
  getScopeCatalog,
  listTokens,
  revokeToken,
  rotateToken,
} from '../../api/tokens';
import HighRiskConfirmDialog from '../common/HighRiskConfirmDialog';
import { useToast } from '../common/Toast';

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

function AccessTokensManager() {
  const toast = useToast();
  const [scope, setScope] = useState('mine');
  const [tokens, setTokens] = useState([]);
  const [catalog, setCatalog] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

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

  // `catalog?.presets || []` built a new array identity on every render, so
  // the selectedPreset memo below it never actually memoized.
  const presets = useMemo(() => catalog?.presets || [], [catalog]);
  const selectedPreset = useMemo(
    () => presets.find((p) => p.key === presetKey) || presets[0],
    [presets, presetKey]
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

  if (loading) return <p>Loading…</p>;

  if (error) {
    return (
      <div role="alert">
        <p>{error}</p>
        <button type="button" className="btn btn-sm" onClick={load}>
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="access-tokens">
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
        <label htmlFor="token-scope">Inventory</label>
        <select id="token-scope" value={scope} onChange={(e) => setScope(e.target.value)}>
          <option value="mine">My tokens</option>
          <option value="all">All tokens</option>
        </select>
      </div>

      {revealed && (
        <div className="access-tokens__reveal">
          <strong>Copy this now. It cannot be shown again.</strong>
          <code>{revealed.token}</code>
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <button
              type="button"
              className="btn btn-sm"
              onClick={() => navigator.clipboard?.writeText(revealed.token)}
            >
              Copy
            </button>
            <button
              type="button"
              className="btn btn-sm btn-primary"
              onClick={() => setRevealed(null)}
            >
              I&apos;ve stored it
            </button>
          </div>
        </div>
      )}

      <table className="entity-table">
        <thead>
          <tr>
            <th>Label</th>
            <th>Type</th>
            <th>Scopes</th>
            <th>Created by</th>
            <th>Expires</th>
            <th>Last used</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {tokens.map((t) => (
            <tr key={t.id} data-testid={`token-row-${t.id}`}>
              <td>{t.label || `token #${t.id}`}</td>
              <td>{t.is_service_account ? 'service account' : 'user token'}</td>
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
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={() => {
                    setConfirmError(null);
                    setConfirm({ mode: 'rotate', token: t });
                  }}
                >
                  Rotate {t.label}
                </button>
                <button
                  type="button"
                  className="btn btn-sm btn-danger"
                  onClick={() => {
                    setConfirmError(null);
                    setConfirm({ mode: 'revoke', token: t });
                  }}
                >
                  Revoke {t.label}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <fieldset style={{ marginTop: 16 }}>
        <legend>Create token</legend>

        <label htmlFor="token-label">Label</label>
        <input id="token-label" value={label} onChange={(e) => setLabel(e.target.value)} />

        <label htmlFor="token-expiry">Expires</label>
        <select
          id="token-expiry"
          value={String(expiryDays)}
          onChange={(e) => setExpiryDays(e.target.value === 'null' ? null : Number(e.target.value))}
        >
          {EXPIRY_OPTIONS.map((o) => (
            <option key={o.label} value={String(o.days)}>
              {o.label}
            </option>
          ))}
        </select>

        <div role="radiogroup" aria-label="Access level">
          {presets.map((p) => (
            <div key={p.key}>
              <input
                type="radio"
                id={`preset-${p.key}`}
                name="token-preset"
                checked={presetKey === p.key}
                onChange={() => setPresetKey(p.key)}
              />
              <label htmlFor={`preset-${p.key}`}>{p.label}</label>
              <span className="access-tokens__hint">
                {p.description} ({p.scopes.join(', ')})
              </span>
            </div>
          ))}
        </div>

        <label>
          <input
            type="checkbox"
            checked={asServiceAccount}
            onChange={(e) => setAsServiceAccount(e.target.checked)}
          />
          Create as a service account (no owning user — outlives its creator)
        </label>

        <button
          type="button"
          className="btn btn-sm btn-primary"
          disabled={creating || !selectedPreset}
          onClick={handleCreate}
        >
          {creating ? 'Creating…' : 'Create token'}
        </button>
      </fieldset>

      <HighRiskConfirmDialog
        open={confirm != null}
        title={confirm?.mode === 'rotate' ? 'Rotate this token' : 'Revoke this token'}
        body={
          confirm?.mode === 'rotate' ? (
            <p>
              A new secret is issued and shown once. The current secret stops working immediately —
              anything still using it will start failing until it is updated.
            </p>
          ) : (
            <p>
              The token stops working immediately and cannot be restored. Anything using it will
              start failing.
            </p>
          )
        }
        confirmPhrase={confirm?.token?.label || ''}
        busy={busy}
        error={confirmError}
        onConfirm={handleConfirmed}
        onCancel={() => setConfirm(null)}
      />
    </div>
  );
}

export default AccessTokensManager;
