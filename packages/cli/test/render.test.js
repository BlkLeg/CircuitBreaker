import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createPhaseRenderer } from '../src/render.js';

test('phase lines use measured duration, remain permanent, and never emit ANSI', () => {
  let text = ''; let clock = 0;
  const renderer = createPhaseRenderer({ write: (s) => { text += s; }, now: () => clock, env: { NO_COLOR: '1' } });
  renderer.phase('verify', 'started'); clock = 2350;
  renderer.phase('verify', 'completed');
  renderer.phase('apply', 'started'); clock = 2650;
  renderer.phase('apply', 'failed');
  assert.equal(text, '✓ verify (2.4s)\n✗ apply (0.3s)\n');
  assert.ok(!text.includes('\x1b'));
});

test('dumb/C terminals use ASCII and progress events do not fabricate success', () => {
  let text = '';
  const renderer = createPhaseRenderer({ write: (s) => { text += s; }, env: { TERM: 'dumb' } });
  renderer.progress('download', 10, 100, 'bytes');
  assert.equal(text, '');
  renderer.phase('download', 'completed');
  renderer.phase('apply', 'failed');
  assert.equal(text, 'OK download\nFAIL apply\n');
});
