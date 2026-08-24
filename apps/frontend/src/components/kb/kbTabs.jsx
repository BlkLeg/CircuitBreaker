import React from 'react';
import * as kbApi from '../../api/kb';
import { formatMacPrefix, isValidMacPrefix, normalizeMacPrefix } from '../../utils/validation';

// What the API actually accepts on PUT. Contract-pinned by
// src/__tests__/kb-tabs.test.js and apps/backend/tests/api/test_kb.py.
// `match_type` is accepted by PUT /kb/hostname/{id} but is deliberately absent
// here: it is an enum, and EntityTable's EditableCell is a bare text input, so
// inline editing it would let an operator store a value the matcher ignores.
// It is edited through the row modal instead.
const INLINE_EDITABLE = ['vendor', 'device_type', 'os_family'];

const MATCH_TYPES = [
  { value: 'prefix', label: 'Prefix' },
  { value: 'exact', label: 'Exact' },
  { value: 'contains', label: 'Contains' },
];

function SourceBadge({ source }) {
  const manual = source === 'manual';
  return (
    <span
      className="tw-inline-block tw-rounded-full tw-px-2 tw-py-0.5 tw-text-xs tw-border"
      style={{
        color: manual ? 'var(--color-success, #3fb950)' : 'var(--color-primary, #4493f8)',
        borderColor: 'var(--color-border, #2a323c)',
      }}
    >
      {source}
    </span>
  );
}

function formatTimestamp(value) {
  if (!value) return '—';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString();
}

const dash = (v) => (v == null || v === '' ? '—' : String(v));

export const KB_TABS = [
  {
    key: 'oui',
    label: 'MAC OUI Prefixes',
    identityKey: 'prefix',
    exportFilename: 'kb-oui.json',
    editableColumns: INLINE_EDITABLE,
    columns: [
      { key: 'prefix', label: 'Prefix', render: (v) => formatMacPrefix(v) },
      { key: 'vendor', label: 'Vendor' },
      { key: 'device_type', label: 'Device type', render: dash },
      { key: 'os_family', label: 'OS family', render: dash },
      { key: 'source', label: 'Source', render: (v) => <SourceBadge source={v} /> },
      { key: 'seen_count', label: 'Seen' },
      { key: 'last_seen_at', label: 'Last seen', render: formatTimestamp },
    ],
    formFields: [
      { name: 'prefix', label: 'MAC prefix (OUI)', required: true },
      { name: 'vendor', label: 'Vendor', required: true },
      { name: 'device_type', label: 'Device type' },
      { name: 'os_family', label: 'OS family' },
    ],
    validateCreate: (values) => {
      if (!isValidMacPrefix(values.prefix)) {
        return { prefix: 'Must be six hexadecimal characters, e.g. B8:27:EB or B827EB.' };
      }
      return null;
    },
    // The backend rejects anything but six bare hex characters, so normalise
    // before sending rather than surfacing a 422 for a conventional spelling.
    serializeCreate: (values) => ({
      ...values,
      prefix: normalizeMacPrefix(values.prefix),
    }),
    api: {
      list: kbApi.listOui,
      create: kbApi.createOui,
      update: kbApi.updateOui,
      remove: kbApi.deleteOui,
      exportAll: kbApi.exportOui,
    },
  },
  {
    key: 'hostname',
    label: 'Hostname Patterns',
    identityKey: 'id',
    exportFilename: 'kb-hostname.json',
    editableColumns: INLINE_EDITABLE,
    columns: [
      { key: 'pattern', label: 'Pattern' },
      { key: 'match_type', label: 'Match' },
      { key: 'vendor', label: 'Vendor', render: dash },
      { key: 'device_type', label: 'Device type', render: dash },
      { key: 'os_family', label: 'OS family', render: dash },
      { key: 'source', label: 'Source', render: (v) => <SourceBadge source={v} /> },
      { key: 'seen_count', label: 'Seen' },
      { key: 'last_seen_at', label: 'Last seen', render: formatTimestamp },
    ],
    formFields: [
      { name: 'pattern', label: 'Hostname pattern', required: true },
      { name: 'match_type', label: 'Match type', type: 'select', options: MATCH_TYPES },
      { name: 'vendor', label: 'Vendor' },
      { name: 'device_type', label: 'Device type' },
      { name: 'os_family', label: 'OS family' },
    ],
    validateCreate: (values) =>
      values.pattern && String(values.pattern).trim()
        ? null
        : { pattern: 'Pattern must not be empty.' },
    serializeCreate: (values) => ({ match_type: 'prefix', ...values }),
    api: {
      list: kbApi.listHostname,
      create: kbApi.createHostname,
      update: kbApi.updateHostname,
      remove: kbApi.deleteHostname,
      exportAll: kbApi.exportHostname,
    },
  },
];
