import React, { useCallback, useEffect, useState } from 'react';
import { KeyRound } from 'lucide-react';
import { getServerKeyStatus, getServerKeyPendingAgents, rotateServerKey } from '../../api/agents';
import HighRiskConfirmDialog from '../common/HighRiskConfirmDialog';
import { useToast } from '../common/Toast';

const SHORT_FP = (fp) => (fp ? `${fp.slice(0, 8)}…${fp.slice(-6)}` : '—');

function formatWhen(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString();
}

function remaining(iso) {
  if (!iso) return null;
  const ms = new Date(iso).getTime() - Date.now();
  if (Number.isNaN(ms) || ms <= 0) return 'expired';
  const days = Math.floor(ms / 86400000);
  const hours = Math.floor((ms % 86400000) / 3600000);
  return days > 0 ? `${days}d ${hours}h` : `${hours}h`;
}

/**
 * Rotation of the key that authenticates the entire agent fleet (INC-13).
 *
 * Copy discipline, per db/models.py:432-450: the server knows only which key
 * each agent's HANDSHAKES have used, never whether the agent holds the
 * successor locally. Nothing here may say an agent "has" the key, and nothing
 * may predict failure for an agent that has not been seen.
 */
function ServerKeyRotationPanel() {
  const toast = useToast();
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [rotating, setRotating] = useState(false);
  const [rotateError, setRotateError] = useState(null);
  const [pending, setPending] = useState(null);
  const [pendingOpen, setPendingOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getServerKeyStatus();
      setStatus(res.data);
    } catch (err) {
      setError(err?.userMessage || 'Could not read the server-key rotation status.');
      setStatus(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleRotate = useCallback(async () => {
    setRotating(true);
    setRotateError(null);
    try {
      await rotateServerKey();
      setConfirmOpen(false);
      toast.success('Rotation started. The successor key was pushed to connected agents.');
      await load();
    } catch (err) {
      if (err?.response?.status === 409) {
        setConfirmOpen(false);
        await load();
        return;
      }
      setRotateError(err?.userMessage || 'Could not start the rotation.');
    } finally {
      setRotating(false);
    }
  }, [toast, load]);

  const showPending = useCallback(async () => {
    setPendingOpen(true);
    if (pending != null) return;
    try {
      const res = await getServerKeyPendingAgents();
      setPending(res.data || []);
    } catch (err) {
      toast.error(err?.userMessage || 'Could not list pending agents.');
      setPendingOpen(false);
    }
  }, [pending, toast]);

  if (loading) return null;

  if (error) {
    return (
      <section className="agents-page__key-panel" role="alert">
        <p>{error}</p>
        <button type="button" className="btn btn-sm" onClick={load}>
          Retry
        </button>
      </section>
    );
  }

  const active = !!status?.active;
  const fleet = status?.fleet;

  return (
    <section className="agents-page__key-panel">
      <header style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <KeyRound size={16} />
        <strong>Agent server key</strong>
        <span className="fleet-muted">
          {active ? 'rotation in progress' : 'no rotation in progress'}
        </span>
        <button
          type="button"
          className="btn btn-sm"
          style={{ marginLeft: 'auto' }}
          disabled={active}
          onClick={() => {
            setRotateError(null);
            setConfirmOpen(true);
          }}
        >
          Rotate key…
        </button>
      </header>

      <dl style={{ display: 'flex', gap: 26, flexWrap: 'wrap', marginTop: 8 }}>
        <div>
          <dt className="fleet-muted">Current fingerprint</dt>
          <dd>{SHORT_FP(status?.current_key_fingerprint)}</dd>
        </div>
        {active && (
          <>
            <div>
              <dt className="fleet-muted">Successor fingerprint</dt>
              <dd>{SHORT_FP(status?.successor_key_fingerprint)}</dd>
            </div>
            <div>
              <dt className="fleet-muted">Started</dt>
              <dd>{formatWhen(status?.started_at)}</dd>
            </div>
            <div>
              <dt className="fleet-muted">Overlap ends</dt>
              <dd>
                {formatWhen(status?.overlap_expires_at)}
                {remaining(status?.overlap_expires_at)
                  ? ` (in ${remaining(status.overlap_expires_at)})`
                  : ''}
              </dd>
            </div>
          </>
        )}
      </dl>

      {active && fleet && (
        <div style={{ marginTop: 12 }}>
          <ul style={{ display: 'flex', gap: 20, listStyle: 'none', padding: 0, margin: 0 }}>
            <li>{fleet.successor} authenticated with successor</li>
            <li>{fleet.current} still on current</li>
            <li>{fleet.unseen} not seen since rotation</li>
          </ul>
          {fleet.current + fleet.unseen > 0 && (
            <button type="button" className="btn btn-sm" onClick={showPending}>
              Show agents
            </button>
          )}
          {pendingOpen && pending && (
            <ul style={{ marginTop: 8 }}>
              {pending.map((a) => (
                <li key={a.id}>
                  {a.hostname || a.name || `Agent ${a.id}`}{' '}
                  <span className="fleet-muted">
                    {a.bucket === 'current' ? 'still on current' : 'not seen since rotation'}
                  </span>
                </li>
              ))}
            </ul>
          )}
          <p className="fleet-muted" style={{ fontSize: 11, marginTop: 8 }}>
            Counts reflect which key each agent&apos;s handshakes have used. The server has no
            visibility into what an agent holds locally.
          </p>
        </div>
      )}

      {active && (
        <p className="fleet-muted" style={{ fontSize: 11, marginTop: 8 }}>
          Rotate is unavailable until the overlap ends — the server allows one rotation in flight.
        </p>
      )}

      <HighRiskConfirmDialog
        open={confirmOpen}
        title="Rotate the agent server key"
        body={
          <>
            <p>
              A fresh successor keypair is generated and pushed immediately to every connected
              agent. Both keys are accepted for a 7-day overlap, after which the current key is
              retired.
            </p>
            <p>
              An agent that stays offline for the entire overlap window will not authenticate once
              it ends, and will need re-enrolling.
            </p>
          </>
        }
        confirmPhrase="ROTATE"
        confirmLabel="Confirm"
        busy={rotating}
        error={rotateError}
        onConfirm={handleRotate}
        onCancel={() => setConfirmOpen(false)}
      />
    </section>
  );
}

export default ServerKeyRotationPanel;
