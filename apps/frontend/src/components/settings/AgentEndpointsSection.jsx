import React, { useEffect, useRef, useState } from 'react';
import PropTypes from 'prop-types';

const S = {
  hint: {
    fontSize: 12,
    color: 'var(--color-text-muted)',
    lineHeight: 1.6,
    margin: '0 0 14px 0',
  },
  row: {
    display: 'flex',
    alignItems: 'flex-end',
    gap: 10,
    padding: '10px 0',
    borderBottom: '1px solid var(--color-border)',
  },
  field: {
    display: 'flex',
    flexDirection: 'column',
    gap: 4,
    fontSize: 12,
    color: 'var(--color-text-muted)',
  },
  labelField: { flex: '0 0 160px' },
  urlField: { flex: 1, minWidth: 0 },
  actions: { display: 'flex', gap: 8, marginTop: 12 },
  error: { fontSize: 12, color: 'var(--color-danger)', marginTop: 8 },
  empty: { fontSize: 12, color: 'var(--color-text-muted)', margin: '0 0 4px 0' },
  usage: { fontSize: 11, color: 'var(--color-text-muted)', marginTop: 4 },
};

// Spec §6 item 4. `undefined` counts mean the read has not resolved; only a
// resolved read with no agents justifies saying none came through, because
// "no agents have enrolled" is a claim about the address, not about the fetch.
function usageLabel(usage, url) {
  if (!usage) return null;
  // `usage` is the server's own count map and `url` a key read out of it, not a path.
  // eslint-disable-next-line security/detect-object-injection
  const count = usage[url] ?? 0;
  if (count === 0) return 'no agents have enrolled through this address yet';
  return `${count} agent${count === 1 ? '' : 's'} enrolled`;
}

/** Client-side row identity, so removing a row does not scramble the ones below it. */
let nextRowKey = 0;

const toRows = (endpoints) =>
  (endpoints ?? []).map((endpoint) => ({
    key: `row-${(nextRowKey += 1)}`,
    id: endpoint.id ?? null,
    label: endpoint.label ?? '',
    url: endpoint.url ?? '',
  }));

/**
 * The addresses agents are told to dial.
 *
 * Separate from `api_base_url` on purpose: that is the browser-facing URL, and
 * the address a browser uses can legitimately differ from the one an agent
 * uses. Getting this wrong is an agent that dials a private address forever
 * and never appears, so the copy says plainly what the field is for.
 */
export default function AgentEndpointsSection({ endpoints = [], usage = null, onSave }) {
  const [rows, setRows] = useState(() => toRows(endpoints));
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState(null);

  // Resync when the parent reloads settings — a row added here comes back with
  // the id the server minted, and without adopting it the next save would ask
  // for a second endpoint instead of editing the first. Compare by value: the
  // parent hands us a fresh array on every render, and resyncing on identity
  // alone would wipe whatever the operator is part-way through typing.
  const lastSynced = useRef(JSON.stringify(endpoints ?? []));
  useEffect(() => {
    const incoming = JSON.stringify(endpoints ?? []);
    if (incoming === lastSynced.current) return;
    lastSynced.current = incoming;
    setRows(toRows(endpoints));
  }, [endpoints]);

  const update = (key, field, value) =>
    setRows((current) =>
      current.map((row) => (row.key === key ? { ...row, [field]: value } : row))
    );

  const handleSave = async () => {
    setIsSaving(true);
    setError(null);
    try {
      // Ids are the server's to mint, so a new row sends none and an existing
      // row keeps the one it has — an install command generated days ago still
      // resolves.
      await onSave(
        rows.map((row) =>
          row.id
            ? { id: row.id, label: row.label, url: row.url }
            : { label: row.label, url: row.url }
        )
      );
    } catch (err) {
      setError(err?.response?.data?.detail ?? err?.message ?? 'Could not save endpoints.');
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div>
      <p style={S.hint}>
        This is the address agents will dial. It is not necessarily the address you use in a browser
        — an agent on another network cannot reach a LAN address. Leave the list empty to keep
        today&apos;s behaviour, where the install command uses whatever host you browsed.
      </p>

      {rows.length === 0 ? <p style={S.empty}>No endpoints configured.</p> : null}

      {rows.map((row) => (
        <div style={S.row} key={row.key}>
          <div style={{ ...S.field, ...S.labelField }}>
            <label htmlFor={`agent-endpoint-label-${row.key}`}>Label</label>
            <input
              id={`agent-endpoint-label-${row.key}`}
              className="form-control"
              type="text"
              value={row.label}
              placeholder="Public"
              onChange={(e) => update(row.key, 'label', e.target.value)}
            />
          </div>
          <div style={{ ...S.field, ...S.urlField }}>
            <label htmlFor={`agent-endpoint-url-${row.key}`}>Address</label>
            <input
              id={`agent-endpoint-url-${row.key}`}
              className="form-control"
              type="text"
              value={row.url}
              placeholder="https://cb.example.com"
              onChange={(e) => update(row.key, 'url', e.target.value)}
            />
            {usageLabel(usage, row.url) ? (
              <span style={S.usage}>{usageLabel(usage, row.url)}</span>
            ) : null}
          </div>
          <button
            type="button"
            className="btn btn-danger btn-sm"
            onClick={() => setRows((current) => current.filter((r) => r.key !== row.key))}
          >
            Remove
          </button>
        </div>
      ))}

      <div style={S.actions}>
        <button
          type="button"
          className="btn btn-sm"
          onClick={() => setRows((current) => [...current, ...toRows([{ label: '', url: '' }])])}
        >
          Add endpoint
        </button>
        <button
          type="button"
          className="btn btn-primary btn-sm"
          onClick={handleSave}
          disabled={isSaving}
        >
          {isSaving ? 'Saving…' : 'Save'}
        </button>
      </div>

      {error ? (
        <p role="alert" style={S.error}>
          {error}
        </p>
      ) : null}
    </div>
  );
}

AgentEndpointsSection.propTypes = {
  endpoints: PropTypes.arrayOf(
    PropTypes.shape({ id: PropTypes.string, label: PropTypes.string, url: PropTypes.string })
  ),
  // Agents enrolled, keyed by endpoint URL. Null until the read resolves.
  usage: PropTypes.objectOf(PropTypes.number),
  onSave: PropTypes.func.isRequired,
};
