/* eslint-disable security/detect-object-injection -- internal key lookups: LIST_FIELDS'/DISCOVERY_NUMBER_FIELDS' own literal keys and its fixed-length draft array */
import React, { useEffect, useState } from 'react';
import PropTypes from 'prop-types';

// Slice 4 Global Constraints, "one capability registry": every bound below is
// the backend's, byte-identical. `_normalize_local_discovery_config` in
// `services/agent_capabilities.py` rejects anything outside these ranges, so a
// value this editor accepts must be a value that endpoint accepts — the checks
// here exist to keep an out-of-range number from reaching the API at all, never
// to define a *different* limit. This table is the only place each pair is
// written: `DISCOVERY_NUMBER_FIELDS` below hands the very same arrays to the
// section's pre-flight guard and to each input's own min/max, so the guard, the
// spinner and the server cannot come to disagree.
export const DISCOVERY_BOUNDS = {
  max_addresses_per_job: [1, 4096],
  max_concurrent_hosts: [1, 256],
  host_timeout_ms: [100, 10000],
  job_timeout_seconds: [30, 1800],
};

// `core/agent_scope.MIN_SCOPE_PREFIX_V4` / `_V6`: the widest prefix that may
// ever be *dispatched*, whatever the grant says. Deliberately not enforced as a
// save-time refusal here — `normalize_scope_cidr` accepts a wider entry and only
// the evaluator refuses it — so this is what makes a wide scope
// confirmation-worthy rather than impossible. Expressed as a minimum prefix
// length because that is the direction the comparison runs.
export const DISCOVERY_MIN_PREFIX_V4 = 16;
export const DISCOVERY_MIN_PREFIX_V6 = 48;

const V4_RE = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\/(\d{1,2})$/;

/**
 * What the evaluator will make of one administrator-typed CIDR.
 *
 * Returns `{valid, version, prefix, addresses, tooWide}` — never throws, and
 * never widens: an entry this cannot parse is reported invalid rather than
 * quietly dropped, because a dropped entry looks saved.
 *
 * IPv6 is judged on its prefix alone. Parsing a full v6 address in the browser
 * to decide ULA membership would be a second, weaker copy of `agent_scope`'s
 * rule, and the server already refuses what it must; the prefix is the only
 * part this file has an opinion about.
 */
export function inspectCidr(value) {
  const text = String(value ?? '').trim();
  if (text.includes(':')) {
    const prefix = Number(text.split('/')[1]);
    if (!Number.isInteger(prefix) || prefix < 0 || prefix > 128) return { valid: false };
    return {
      valid: true,
      version: 6,
      prefix,
      addresses: 2 ** (128 - prefix),
      tooWide: prefix < DISCOVERY_MIN_PREFIX_V6,
      minPrefix: DISCOVERY_MIN_PREFIX_V6,
    };
  }
  const match = V4_RE.exec(text);
  if (!match) return { valid: false };
  const octets = match.slice(1, 5).map(Number);
  const prefix = Number(match[5]);
  if (octets.some((octet) => octet > 255) || prefix > 32) return { valid: false };
  return {
    valid: true,
    version: 4,
    prefix,
    addresses: 2 ** (32 - prefix),
    tooWide: prefix < DISCOVERY_MIN_PREFIX_V4,
    minPrefix: DISCOVERY_MIN_PREFIX_V4,
  };
}

// The list-valued settings, in the order the registry declares them. Rendered
// from this list rather than from `Object.keys(config)` so a scalar the server
// adds later doesn't silently become a comma-separated text box.
//
// There is deliberately no `additional_hostnames` here, unlike `remote_probe`:
// discovery targets are prefixes, and a name written here would look approved
// while never matching anything.
const LIST_FIELDS = [
  {
    key: 'additional_cidrs',
    label: 'Routed overrides',
    hint: 'Networks this agent may discover beyond its own directly connected ones.',
  },
  {
    key: 'excluded_cidrs',
    label: 'Excluded CIDRs',
    hint: 'Carved out of the derived scope. Special-use ranges are always blocked regardless.',
  },
  {
    key: 'tcp_ports',
    label: 'Scan depth (TCP ports)',
    hint: 'The ports the connect sweep tries on each responding host. At most 32.',
    numeric: true,
  },
];

// The scalar settings, each carrying the label the operator reads and the bound
// pair from the table above — by reference, never re-typed. Exported because
// `DiscoveryScopeSection`'s guard needs both halves: the same numbers the input
// enforces, and the same words the input is labelled with, so its refusal names
// the field the operator is looking at.
export const DISCOVERY_NUMBER_FIELDS = [
  { key: 'max_addresses_per_job', label: 'Addresses per job' },
  { key: 'max_concurrent_hosts', label: 'Concurrent hosts' },
  { key: 'host_timeout_ms', label: 'Host timeout (ms)' },
  { key: 'job_timeout_seconds', label: 'Job timeout (seconds)' },
].map((field) => ({ ...field, bounds: DISCOVERY_BOUNDS[field.key] }));

const joinList = (value) => (Array.isArray(value) ? value.join(', ') : '');
const splitList = (text, numeric) =>
  text
    .split(',')
    .map((entry) => entry.trim())
    .filter(Boolean)
    .map((entry) => (numeric ? Number(entry) : entry));

/**
 * The `local_discovery` grant's structured config (plan §1, §6).
 *
 * Presentational, exactly as `RemoteProbeConfigEditor` is: every edit is handed
 * to `onChange(patch)`, which owns the write, the confirmation and the
 * re-sync. That split is deliberate — a wide scope needs a ConfirmDialog the
 * section renders, and rolling back needs the whole agent record, which this
 * component does not hold.
 *
 * `defaults` is the server registry's config for the capability
 * (GET /agents/capability-defaults), never a local copy: a key the server grows
 * later still gets a sensible fallback here without a frontend change.
 */
export default function LocalDiscoveryConfigEditor({ config, defaults, onChange, disabled }) {
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

  const commitList = (index, field) => {
    const next = splitList(drafts[index], field.numeric);
    if (JSON.stringify(next) === JSON.stringify(merged[field.key] ?? [])) return;
    onChange({ [field.key]: next });
  };

  return (
    <fieldset className="agent-discovery__config">
      <legend>Local discovery settings</legend>
      {/* `direct_private` is the only mode the registry declares (SCOPE_MODES is
          a one-element frozenset), so this is a readout, not a control — the
          same call `RemoteProbeConfigEditor` makes for the same reason. */}
      <p className="agent-discovery__scope-mode">
        Scope mode: <code>{merged.scope_mode ?? '—'}</code> — derived from the networks this agent
        reports, so a directly connected subnet needs no scope edit.
      </p>
      {DISCOVERY_NUMBER_FIELDS.map((field) => (
        <label key={field.key}>
          {field.label}{' '}
          <input
            type="number"
            min={field.bounds[0]}
            max={field.bounds[1]}
            disabled={disabled}
            value={merged[field.key] ?? ''}
            onChange={(event) => onChange({ [field.key]: Number(event.target.value) })}
          />
        </label>
      ))}
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
            onBlur={() => commitList(index, field)}
          />
          <span className="agent-discovery__hint">{field.hint}</span>
        </label>
      ))}
    </fieldset>
  );
}

LocalDiscoveryConfigEditor.propTypes = {
  config: PropTypes.object,
  defaults: PropTypes.object,
  onChange: PropTypes.func.isRequired,
  disabled: PropTypes.bool,
};
