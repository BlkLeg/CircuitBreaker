import React, { useCallback, useEffect, useState } from 'react';

import { listEnrollmentTokens, revokeEnrollmentToken } from '../../api/agents';
import { operatorErrorMessage } from '../../lib/agentErrors';

const S = {
  hint: {
    fontSize: 12,
    color: 'var(--color-text-muted)',
    lineHeight: 1.6,
    margin: '0 0 14px 0',
  },
  table: { width: '100%', borderCollapse: 'collapse', fontSize: 12 },
  th: {
    textAlign: 'left',
    padding: '6px 8px',
    color: 'var(--color-text-muted)',
    borderBottom: '1px solid var(--color-border)',
    fontWeight: 500,
  },
  td: { padding: '8px', borderBottom: '1px solid var(--color-border)', verticalAlign: 'top' },
  url: { color: 'var(--color-text-muted)', wordBreak: 'break-all' },
  muted: { fontSize: 12, color: 'var(--color-text-muted)', margin: '0 0 4px 0' },
  error: { fontSize: 12, color: 'var(--color-danger)', marginTop: 8 },
};

const LIVE = 'Live';

/**
 * What an operator can still do about a token.
 *
 * Revoked wins over expired and spent: a token that was revoked and has since
 * lapsed is, to anyone auditing it, the one somebody deliberately shut off.
 * Only a `Live` token can be revoked — the rest are already inert, and offering
 * the button would suggest otherwise.
 */
function tokenState(token) {
  if (token.revoked_at) return 'Revoked';
  if (Date.parse(token.expires_at) <= Date.now()) return 'Expired';
  if (token.uses >= token.max_uses) return 'Spent';
  return LIVE;
}

function agentsLabel(count) {
  return `${count} agent${count === 1 ? '' : 's'} enrolled`;
}

/**
 * Slice B: the enrollment tokens an operator has minted, and the one action
 * they can still take on them.
 *
 * The design names only the add-agent wizard as a surface, but it also gives
 * tokens a revoke endpoint — and a revoke nothing can reach is a capability
 * with no way to use it. This is the minimum that makes it real: a list and a
 * button, not a management console.
 *
 * No token value is ever shown. The server stores only a SHA-256, so there is
 * nothing here to leak even if this were rendered somewhere it should not be.
 */
export default function EnrollmentTokensSection() {
  const [tokens, setTokens] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [revokingId, setRevokingId] = useState(null);

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      const { data } = await listEnrollmentTokens();
      setTokens(data ?? []);
    } catch (err) {
      setLoadError(
        operatorErrorMessage(err, {
          fallback: 'Could not read enrollment tokens',
          forbidden: 'Ask an administrator to manage enrollment tokens',
        })
      );
      setTokens([]);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleRevoke = async (id) => {
    setRevokingId(id);
    setActionError(null);
    try {
      const { data } = await revokeEnrollmentToken(id);
      // Splice the server's own row back in rather than re-fetching: the
      // response is the authoritative post-revoke state, and a refetch would
      // reorder the table under the operator's cursor.
      setTokens((rows) => (rows ?? []).map((row) => (row.id === id ? data : row)));
    } catch (err) {
      setActionError(
        operatorErrorMessage(err, {
          fallback: 'Could not revoke that token',
          forbidden: 'Ask an administrator to revoke enrollment tokens',
        })
      );
    } finally {
      setRevokingId(null);
    }
  };

  if (tokens === null) {
    return <p style={S.muted}>Loading enrollment tokens…</p>;
  }

  return (
    <div>
      <p style={S.hint}>
        Tokens let a machine enrol without anyone approving it here. Each one is scoped to a single
        endpoint and expires on its own; revoking one does not disturb agents that already enrolled
        through it. Mint one from <strong>Agents → Add agent</strong>.
      </p>

      {loadError && (
        <p style={S.error} role="alert">
          {loadError}
        </p>
      )}

      {tokens.length === 0 && !loadError ? (
        <p style={S.muted}>No enrollment tokens have been created.</p>
      ) : (
        <table style={S.table}>
          <thead>
            <tr>
              <th style={S.th}>Label</th>
              <th style={S.th}>Endpoint</th>
              <th style={S.th}>Uses</th>
              <th style={S.th}>Agents</th>
              <th style={S.th}>State</th>
              <th style={S.th} aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {tokens.map((token) => {
              const state = tokenState(token);
              return (
                <tr key={token.id}>
                  <td style={S.td}>{token.label}</td>
                  <td style={{ ...S.td, ...S.url }}>{token.endpoint_url}</td>
                  <td style={S.td}>{`${token.uses} / ${token.max_uses}`}</td>
                  <td style={S.td}>{agentsLabel(token.agent_count)}</td>
                  <td style={S.td}>{state}</td>
                  <td style={S.td}>
                    {state === LIVE && (
                      <button
                        type="button"
                        onClick={() => handleRevoke(token.id)}
                        disabled={revokingId === token.id}
                      >
                        {revokingId === token.id ? 'Revoking…' : 'Revoke'}
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {actionError && (
        <p style={S.error} role="alert">
          {actionError}
        </p>
      )}
    </div>
  );
}
