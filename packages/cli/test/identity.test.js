import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { readFileSync } from 'node:fs';
import { candidatePaths, loadIdentity, validateIdentity } from '../src/identity.js';

const SHELL_LIB = fileURLToPath(new URL('../../../deploy/lib/install-identity.sh', import.meta.url));
const SCHEMA = JSON.parse(readFileSync(new URL('../schemas/install-identity.schema.json', import.meta.url), 'utf8'));
const VALID = { schema_version: 1, mode: 'native', version: '0.4.7', installed_at: '2026-09-30T00:00:00Z', cli_path: '/usr/local/bin/cb' };

function fakeFs(files) {
  return async (path) => {
    if (!(path in files)) throw Object.assign(new Error('nope'), { code: 'ENOENT' });
    const value = files[path];
    if (value instanceof Error) throw value;
    return value;
  };
}

test('search order is identical to the shell library cb uses', () => {
  for (const env of [{}, { CB_DATA_DIR: '/srv/cb' }, { CB_DATA_DIR: '/srv/cb/' }]) {
    const shell = execFileSync('bash', ['-c', 'source "$1"; cb_identity_candidate_paths', 'bash', SHELL_LIB], {
      env: { PATH: process.env.PATH, HOME: '/home/tester', ...env },
      encoding: 'utf8',
    }).trim().split('\n');
    assert.deepEqual(candidatePaths({ env, home: '/home/tester' }), shell, JSON.stringify(env));
  }
});

test('an explicit CB_IDENTITY_PATH is the only path searched, as in cb', async () => {
  const lookup = await loadIdentity({ env: { CB_IDENTITY_PATH: '/x/id.json' }, home: '/h', readFile: fakeFs({}) });
  assert.deepEqual(lookup, { status: 'missing', searched: ['/x/id.json'] });
});

test('the first readable candidate wins', async () => {
  const readFile = fakeFs({ '/etc/circuit-breaker/install-identity.json': JSON.stringify(VALID) });
  const lookup = await loadIdentity({ env: {}, home: '/h', readFile });
  assert.equal(lookup.status, 'found');
  assert.equal(lookup.path, '/etc/circuit-breaker/install-identity.json');
  assert.equal(lookup.identity.version, '0.4.7');
});

test('an unreadable candidate is reported when nothing readable is found', async () => {
  const denied = Object.assign(new Error('denied'), { code: 'EACCES' });
  const lookup = await loadIdentity({ env: {}, home: '/h', readFile: fakeFs({ '/etc/circuitbreaker/install-identity.json': denied }) });
  assert.equal(lookup.status, 'unreadable');
  assert.equal(lookup.path, '/etc/circuitbreaker/install-identity.json');
});

test('an unreadable candidate does not hide a readable later one', async () => {
  const denied = Object.assign(new Error('denied'), { code: 'EACCES' });
  const readFile = fakeFs({
    '/etc/circuitbreaker/install-identity.json': denied,
    '/h/.circuit-breaker/install-identity.json': JSON.stringify(VALID),
  });
  assert.equal((await loadIdentity({ env: {}, home: '/h', readFile })).status, 'found');
});

test('malformed JSON and schema violations are invalid, with reasons', async () => {
  const path = '/etc/circuitbreaker/install-identity.json';
  const broken = await loadIdentity({ env: {}, home: '/h', readFile: fakeFs({ [path]: '{' }) });
  assert.deepEqual(broken, { status: 'invalid', path, problems: ['not valid JSON'] });
  const bad = await loadIdentity({ env: {}, home: '/h', readFile: fakeFs({ [path]: JSON.stringify({ ...VALID, mode: 'k8s' }) }) });
  assert.equal(bad.status, 'invalid');
  assert.match(bad.problems.join(), /mode/);
});

test('validator enforces required, const, enum, minLength, types, items and unknown keys', () => {
  assert.deepEqual(validateIdentity(VALID), []);
  assert.match(validateIdentity(null).join(), /not a JSON object/);
  assert.match(validateIdentity([]).join(), /not a JSON object/);
  const { installed_at, ...noStamp } = VALID;
  assert.match(validateIdentity(noStamp).join(), /installed_at/);
  assert.match(validateIdentity({ ...VALID, schema_version: 2 }).join(), /schema_version/);
  assert.match(validateIdentity({ ...VALID, schema_version: '1' }).join(), /integer/);
  assert.match(validateIdentity({ ...VALID, version: '' }).join(), /version/);
  assert.match(validateIdentity({ ...VALID, service_names: ['ok', ''] }).join(), /service_names\[1\]/);
  assert.match(validateIdentity({ ...VALID, service_names: 'x' }).join(), /array/);
  assert.match(validateIdentity({ ...VALID, surprise: 1 }).join(), /unknown field 'surprise'/);
});

test('the validator understands every keyword the schema uses', () => {
  const supported = new Set(['type', 'const', 'enum', 'minLength', 'items', 'description']);
  const used = new Set();
  const walk = (rule) => {
    for (const [k, v] of Object.entries(rule)) {
      used.add(k);
      if (k === 'items') walk(v);
    }
  };
  Object.values(SCHEMA.properties).forEach(walk);
  assert.deepEqual([...used].filter((k) => !supported.has(k)), []);
});
