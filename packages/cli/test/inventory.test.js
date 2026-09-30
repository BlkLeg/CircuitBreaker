import { test } from 'node:test';
import assert from 'node:assert/strict';
import { NATIVE_COMMANDS, findNativeCommand } from '../src/inventory.js';
import { managementCompatibility } from '../src/compat.js';

test('inventory names are unique and every entry has a summary', () => {
  const names = NATIVE_COMMANDS.map((c) => c.name);
  assert.equal(new Set(names).size, names.length);
  for (const c of NATIVE_COMMANDS) assert.ok(c.summary.length > 0, c.name);
});

test('only update and uninstall are lifecycle commands', () => {
  assert.deepEqual(NATIVE_COMMANDS.filter((c) => c.lifecycle).map((c) => c.name).sort(), ['uninstall', 'update']);
});

test('findNativeCommand returns entries and null for strangers', () => {
  assert.equal(findNativeCommand('status').name, 'status');
  assert.equal(findNativeCommand('rm'), null);
  assert.equal(findNativeCommand('__proto__'), null);
});

test('the CLI always certifies its own release', () => {
  assert.deepEqual(managementCompatibility('9.9.9', '9.9.9'), { certified: true, reason: 'same release as this CLI' });
});

test('listed older servers are certified; unknown and newer ones are not', () => {
  assert.equal(managementCompatibility('0.4.5', '0.4.7').certified, true);
  const unknown = managementCompatibility('0.3.0', '0.4.7');
  assert.equal(unknown.certified, false);
  assert.match(unknown.reason, /0\.3\.0/);
  assert.equal(managementCompatibility('0.5.0', '0.4.7').certified, false);
});
