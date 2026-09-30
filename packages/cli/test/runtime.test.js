import { test } from 'node:test';
import assert from 'node:assert/strict';
import { unsupportedRuntime, MIN_NODE_MAJOR } from '../src/runtime.js';
import { EXIT } from '../src/exit-codes.js';

test('a supported Linux host with Node 22+ passes', () => {
  assert.equal(unsupportedRuntime({ platform: 'linux', nodeVersion: '22.11.0' }), null);
  assert.equal(unsupportedRuntime({ platform: 'linux', nodeVersion: '24.0.0' }), null);
});

test('Node older than the floor is refused with the versions named', () => {
  const message = unsupportedRuntime({ platform: 'linux', nodeVersion: '20.20.2' });
  assert.match(message, /Node\.js 22 or newer/);
  assert.match(message, /20\.20\.2/);
  assert.equal(MIN_NODE_MAJOR, 22);
});

test('non-Linux hosts are refused before the Node check', () => {
  for (const platform of ['darwin', 'win32', 'freebsd']) {
    assert.match(unsupportedRuntime({ platform, nodeVersion: '24.0.0' }), new RegExp(`Linux only.*${platform}`));
  }
});

test('an unparseable version is refused, not treated as new enough', () => {
  assert.match(unsupportedRuntime({ platform: 'linux', nodeVersion: 'garbage' }), /Node\.js 22/);
});

test('exit codes match the design table exactly', () => {
  assert.deepEqual({ ...EXIT }, {
    OK: 0, USAGE: 2, UNSUPPORTED: 3, NETWORK: 4, TRUST: 5, PERMISSION: 6,
    PREFLIGHT: 7, RECOVERED: 8, MANUAL: 9, LOCKED: 10, INTERRUPTED: 130,
  });
  assert.ok(Object.isFrozen(EXIT));
});
