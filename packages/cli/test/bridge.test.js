import { test } from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { mkdtemp, writeFile, chmod, readFile, access } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';
import { forwardToNative, FORWARD_MARKER } from '../src/bridge.js';

async function fake(body) {
  const dir = await mkdtemp(join(tmpdir(), 'cb-bridge-'));
  const file = join(dir, 'cb');
  await writeFile(file, `#!/usr/bin/env node\n${body}\n`);
  await chmod(file, 0o755);
  return { dir, file };
}

async function waitFor(path) {
  for (let i = 0; i < 100; i += 1) {
    try { await access(path); return; } catch { await sleep(50); }
  }
  throw new Error(`${path} never appeared`);
}

const quiet = () => ({ ...process.env });

test('arguments arrive verbatim, shell syntax included, with the loop marker set', async () => {
  const { dir, file } = await fake(
    `require('node:fs').writeFileSync(process.env.OUT, JSON.stringify({ argv: process.argv.slice(2), marker: process.env.${FORWARD_MARKER} }));`,
  );
  const out = join(dir, 'out.json');
  const pwned = join(dir, 'pwned');
  const args = ['token', 'create', '--name', `$(touch ${pwned})`, '; rm -rf /', '--', '-f', ''];
  const code = await forwardToNative({ cliPath: file, args, env: { ...quiet(), OUT: out }, proc: new EventEmitter() });
  assert.equal(code, 0);
  assert.deepEqual(JSON.parse(await readFile(out, 'utf8')), { argv: args, marker: '1' });
  await assert.rejects(access(pwned));
});

test("the child's exit code is returned unchanged", async () => {
  const { file } = await fake('process.exit(3);');
  assert.equal(await forwardToNative({ cliPath: file, args: [], env: quiet(), proc: new EventEmitter() }), 3);
});

test('death by signal maps to 128 + signal number', async () => {
  const { file: term } = await fake("process.kill(process.pid, 'SIGTERM');");
  assert.equal(await forwardToNative({ cliPath: term, args: [], env: quiet(), proc: new EventEmitter() }), 143);
  const { file: int } = await fake("process.kill(process.pid, 'SIGINT');");
  assert.equal(await forwardToNative({ cliPath: int, args: [], env: quiet(), proc: new EventEmitter() }), 130);
});

test('SIGINT to the launcher is left to the child; SIGTERM is relayed', async () => {
  const { dir: dir1, file: file1 } = await fake(`
    const fs = require('node:fs');
    process.on('SIGTERM', () => process.exit(42));
    fs.writeFileSync(process.env.READY, '');
    setTimeout(() => process.exit(7), 400);
  `);
  const proc = new EventEmitter();
  const ready = join(dir1, 'ready');
  const pending = forwardToNative({ cliPath: file1, args: [], env: { ...quiet(), READY: ready }, proc });
  await waitFor(ready);
  proc.emit('SIGINT');
  assert.equal(await pending, 7, 'SIGINT must not kill the child from the launcher side');
  assert.equal(proc.listenerCount('SIGINT'), 0);
  assert.equal(proc.listenerCount('SIGTERM'), 0);

  const { dir: dir2, file: file2 } = await fake(`
    const fs = require('node:fs');
    process.on('SIGTERM', () => process.exit(42));
    fs.writeFileSync(process.env.READY, '');
    setInterval(() => {}, 1 << 30);
  `);
  const ready2 = join(dir2, 'ready2');
  const relayed = forwardToNative({ cliPath: file2, args: [], env: { ...quiet(), READY: ready2 }, proc });
  await waitFor(ready2);
  proc.emit('SIGTERM');
  assert.equal(await relayed, 42);
});

test('an unexecutable path rejects with the spawn error code', async () => {
  const { file } = await fake('');
  await chmod(file, 0o644);
  await assert.rejects(
    forwardToNative({ cliPath: file, args: [], env: quiet(), proc: new EventEmitter() }),
    (error) => error.code === 'EACCES',
  );
});
