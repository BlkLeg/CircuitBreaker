/* eslint-disable security/detect-object-injection -- internal key lookups: LIST_FIELDS' own literal keys and its fixed-length draft array */
import React, { useEffect, useState } from 'react';
import PropTypes from 'prop-types';

// Slice 3 Global Constraints, "one capability registry": these bounds are the
// backend's, byte-identical. `_normalize_remote_probe_config` in
// `services/agent_capabilities.py` rejects anything outside 1..100, so a value
// this editor accepts must be a value that endpoint accepts — the check here
// exists to keep an out-of-range number from reaching the API at all, never to
// define a *different* limit. Exported so AgentDetailPage's guard and the
// input's own min/max share one number instead of three copies.
export const REMOTE_PROBE_MIN_CONCURRENT = 1;
export const REMOTE_PROBE_MAX_CONCURRENT = 100;

// The list-valued settings, in the order the registry declares them. Rendered
// from this list rather than from `Object.keys(config)` so a scalar the server
// adds later doesn't silently become a comma-separated text box.
const LIST_FIELDS = [
  {
    key: 'additional_cidrs',
    label: 'Additional CIDRs',
    hint: 'Routed networks this agent may probe beyond its own directly connected ones.',
  },
  {
    key: 'excluded_cidrs',
    label: 'Excluded CIDRs',
    hint: 'Carved out of the derived scope. Special-use ranges are always blocked regardless.',
  },
  {
    key: 'additional_hostnames',
    label: 'Additional hostnames',
    hint: 'Hostname rules, one per entry; a leading "*." matches subdomains.',
  },
];

const joinList = (value) => (Array.isArray(value) ? value.join(', ') : '');
const splitList = (text) =>
  text
    .split(',')
    .map((entry) => entry.trim())
    .filter(Boolean);

/**
 * The `remote_probe` grant's structured config (design §3).
 *
 * Presentational: every edit is handed to `onChange(patch)`, which owns the
 * optimistic update and the rollback. That split is deliberate — the rollback
 * has to restore the whole agent record, which only the page holds.
 *
 * `defaults` is the server registry's config for the capability
 * (GET /agents/capability-defaults), never a local copy: a key the server grows
 * later still gets a sensible fallback here without a frontend change, exactly
 * as the host-telemetry editor above it works.
 */
export default function RemoteProbeConfigEditor({ config, defaults, onChange, disabled }) {
  const merged = { ...defaults, ...config };
  // Lists commit on blur, not per keystroke, so a half-typed CIDR is never
  // sent. The drafts are re-seeded whenever the persisted config changes —
  // including when it changes *back*, which is what a rejected edit does, so a
  // rolled-back value leaves the text box showing what is really stored rather
  // than the string the server refused.
  const serialized = JSON.stringify(LIST_FIELDS.map((field) => merged[field.key] ?? []));
  const [drafts, setDrafts] = useState(() => JSON.parse(serialized).map(joinList));
  useEffect(() => {
    setDrafts(JSON.parse(serialized).map(joinList));
  }, [serialized]);

  const commitList = (index, key) => {
    const next = splitList(drafts[index]);
    if (JSON.stringify(next) === JSON.stringify(merged[key] ?? [])) return;
    onChange({ [key]: next });
  };

  return (
    <fieldset className="agent-probes__config">
      <legend>Remote probe settings</legend>
      <label>
        Concurrent checks{' '}
        <input
          type="number"
          min={REMOTE_PROBE_MIN_CONCURRENT}
          max={REMOTE_PROBE_MAX_CONCURRENT}
          disabled={disabled}
          value={merged.max_concurrent ?? ''}
          onChange={(event) => onChange({ max_concurrent: Number(event.target.value) })}
        />
      </label>
      {/* `direct_private` is the only mode the registry declares (SCOPE_MODES
          is a one-element frozenset), so this is a readout, not a control. A
          select with a single option would imply a choice that does not exist
          and would be the first thing to drift when Slice 4 adds one. */}
      <p className="agent-probes__scope-mode">
        Scope mode: <code>{merged.scope_mode ?? '—'}</code> — derived from the networks this agent
        reports, so a directly connected target needs no scope edit.
      </p>
      {LIST_FIELDS.map((field, index) => (
        <label key={field.key}>
          {field.label}{' '}
          <input
            type="text"
            disabled={disabled}
            value={drafts[index] ?? ''}
            placeholder="comma separated"
            onChange={(event) =>
              setDrafts((current) =>
                current.map((entry, position) => (position === index ? event.target.value : entry))
              )
            }
            onBlur={() => commitList(index, field.key)}
          />
          <span className="agent-probes__hint">{field.hint}</span>
        </label>
      ))}
    </fieldset>
  );
}

RemoteProbeConfigEditor.propTypes = {
  config: PropTypes.object,
  defaults: PropTypes.object,
  onChange: PropTypes.func.isRequired,
  disabled: PropTypes.bool,
};
