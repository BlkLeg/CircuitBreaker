import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), '..');

// Circuit Breaker 1.0 is single-tenant per deployment (ADR-0003, and
// api/tenants.py answers 410 Gone). SEC-05 requires that a user cannot
// "infer a security boundary that is not provided" — which includes error
// copy describing one.
const FILES_WITH_AGENT_MISMATCH_COPY = [
  'components/monitors/RunFromSelect.jsx',
  'components/discovery/ScanProfileForm.jsx',
];

describe('single-tenant user-facing copy', () => {
  it.each(FILES_WITH_AGENT_MISMATCH_COPY)('does not tell the user about tenants in %s', (rel) => {
    // eslint-disable-next-line security/detect-non-literal-fs-filename -- rel comes from this file's own literal file list
    const source = readFileSync(resolve(SRC, rel), 'utf8');
    expect(source).not.toMatch(/different tenant/i);
  });
});
