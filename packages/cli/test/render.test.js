import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createPhaseRenderer } from '../src/render.js';
import { EventEmitter } from 'node:events';
import { readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { ART } from '../src/art.js';

test('the npm artwork is byte-identical to the native cb_logo figure', () => {
  const installer = readFileSync(new URL('../../../install.sh', import.meta.url), 'utf8');
  const start = installer.indexOf('cb_logo() {');
  const body = installer.slice(start, installer.indexOf('  # cb_version reports', start));
  assert.equal(ART, execFileSync('bash', ['-c', `${body}}\ncb_logo\n`], { encoding: 'utf8' }));
});

test('foreign partial output is preserved and prevents live redraw until its newline', () => {
  let text = ''; let clock = 0;
  const r = createPhaseRenderer({ write: s => { text += s; }, now: () => clock, terminal: { isTTY: true, columns: 100, rows: 30 }, env: { TERM: 'xterm' }, schedule: () => ({ unref() {} }), cancel() {} });
  r.phase('download', 'started');
  r.output('partial native record');
  const before = text; clock = 150; r.tick();
  assert.equal(text, before);
  r.output(' completed\n'); clock = 300; r.tick();
  assert.ok(text.includes('partial native record completed\n'));
  r.close();
});

test('TTY progress uses measured bytes, redraws at most 8Hz and survives resize and interruption', () => {
  let text = ''; let clock = 0; const terminal = new EventEmitter();
  Object.assign(terminal, { isTTY: true, columns: 90, rows: 30 });
  const proc = new EventEmitter();
  const r = createPhaseRenderer({ write: s => { text += s; }, now: () => clock, env: { TERM: 'xterm' }, terminal, proc, schedule: () => ({ unref() {} }), cancel() {} });
  r.phase('download', 'started');
  for (let i = 1; i < 125; i++) { clock = i; r.progress('download', i, 1000, 'bytes'); }
  assert.equal((text.match(/\x1b\[2K/g) ?? []).length, 0);
  clock = 125; r.tick();
  assert.match(text, /124 B \/ 1000 B/);
  assert.doesNotMatch(text, /committed|healthy|100%/);
  terminal.columns = 25; terminal.emit('resize'); clock = 250; r.tick();
  assert.ok(r.liveText().length <= 24);
  proc.emit('SIGTERM'); r.close();
  assert.ok(text.endsWith('\x1b[?25h'));
  assert.equal(proc.listenerCount('SIGTERM'), 0);
  assert.equal(terminal.listenerCount('resize'), 0);
});

test('static TTY emits phases without motion; results distinguish recovery from success and redact secrets', () => {
  let text = ''; const r = createPhaseRenderer({ write: s => { text += s; }, terminal: { isTTY: true, columns: 80 }, env: { TERM: 'xterm', CB_NO_ANIMATION: '1', NO_COLOR: '1' } });
  r.phase('apply', 'started'); r.phase('apply', 'failed');
  r.result({ action: 'update', outcome: 'recovered', current_version: '0.4.6', target_version: '0.4.7', operation_id: 'op-20261002-123', recovery_available: true, error: { reason: 'CB_TOKEN=secretvalue' } });
  r.close();
  assert.ok(!text.includes('\x1b'));
  assert.match(text, /RECOVERED/); assert.doesNotMatch(text, /UPDATE COMPLETE|secretvalue/);
  assert.match(text, /0.4.6/); assert.match(text, /cb doctor/);
});

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

test('the summary names what ran before the operation, not what runs after it', () => {
  const summary = (previousVersion) => {
    let text = ''; const r = createPhaseRenderer({ write: s => { text += s; }, terminal: { isTTY: false }, env: { NO_COLOR: '1' } });
    r.heading('install', previousVersion, '0.4.7');
    r.result({ action: 'install', outcome: 'committed', current_version: '0.4.7', target_version: '0.4.7', operation_id: 'op-20261002-001', recovery_available: false });
    r.close();
    return text;
  };
  assert.match(summary(undefined), /Previous: none \(new install\)/);
  assert.match(summary('0.4.6'), /Previous: 0\.4\.6\n {2}Target: {3}0\.4\.7/);
});
