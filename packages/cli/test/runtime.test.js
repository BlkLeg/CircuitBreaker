import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { unsupportedRuntime, NODE_ENGINES } from '../src/runtime.js';
import { EXIT } from '../src/exit-codes.js';

const linux = (nodeVersion) => unsupportedRuntime({ platform: 'linux', nodeVersion });

test('Node inside the sigstore 5 engines range passes', () => {
  for (const version of ['22.22.2', '22.23.3', '24.15.0', '24.20.1', '26.0.0', '27.3.1']) {
    assert.equal(linux(version), null, version);
  }
});

test('Node outside the range is refused with the floors and the running version named', () => {
  for (const version of ['20.20.2', '22.11.0', '22.22.1', '23.1.0', '24.0.0', '24.14.9', '25.9.0']) {
    const message = linux(version);
    assert.equal(message, `Node.js 22.22.2+, 24.15.0+ or 26+ is required; this is ${version}.`);
  }
});

test('the launcher check and package.json engines state the same range', () => {
  const manifest = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'));
  assert.equal(NODE_ENGINES, '^22.22.2 || ^24.15.0 || >=26.0.0');
  assert.equal(manifest.engines.node, NODE_ENGINES);
});

test('non-Linux hosts are refused before the Node check', () => {
  for (const platform of ['darwin', 'win32', 'freebsd']) {
    assert.match(unsupportedRuntime({ platform, nodeVersion: '24.15.0' }), new RegExp(`Linux only.*${platform}`));
  }
});

test('an unparseable version is refused, not treated as new enough', () => {
  for (const version of ['garbage', '24', '24.15', '']) {
    assert.match(linux(version), /Node\.js 22\.22\.2\+/, version);
  }
});

test('exit codes match the design table exactly', () => {
  assert.deepEqual({ ...EXIT }, {
    OK: 0, USAGE: 2, UNSUPPORTED: 3, NETWORK: 4, TRUST: 5, PERMISSION: 6,
    PREFLIGHT: 7, RECOVERED: 8, MANUAL: 9, LOCKED: 10, INTERRUPTED: 130,
  });
  assert.ok(Object.isFrozen(EXIT));
});
