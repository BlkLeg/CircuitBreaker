import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, chmod, symlink, mkdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { checkTrustedFile } from '../src/trust.js';

const me = [process.getuid()];

async function sandbox() {
  const dir = await mkdtemp(join(tmpdir(), 'cb-trust-'));
  const file = join(dir, 'cb');
  await writeFile(file, '#!/bin/sh\n');
  await chmod(file, 0o755);
  return { dir, file };
}

test('a private, owned, executable file is trusted and resolved', async () => {
  const { file } = await sandbox();
  assert.deepEqual(await checkTrustedFile(file, { trustedUids: me, executable: true }), { ok: true, path: file });
});

test('relative paths are refused', async () => {
  const result = await checkTrustedFile('bin/cb', { trustedUids: me });
  assert.equal(result.ok, false);
  assert.match(result.reason, /not an absolute path/);
});

test('a file owned by an untrusted uid is refused', async () => {
  const { file } = await sandbox();
  const result = await checkTrustedFile(file, { trustedUids: [0], executable: true });
  assert.equal(result.ok, false);
  assert.match(result.reason, /owned by uid/);
});

test('a group- or world-writable file is refused', async () => {
  const { file } = await sandbox();
  await chmod(file, 0o775);
  assert.match((await checkTrustedFile(file, { trustedUids: me })).reason, /writable by group or others/);
});

test('a file in a world-writable directory is refused', async () => {
  const { dir } = await sandbox();
  const open = join(dir, 'open');
  await mkdir(open, { mode: 0o777 });
  await chmod(open, 0o777);
  const file = join(open, 'cb');
  await writeFile(file, '#!/bin/sh\n', { mode: 0o755 });
  assert.match((await checkTrustedFile(file, { trustedUids: me })).reason, /directory .* writable by group or others/);
});

test('a non-executable file is refused when execution is required', async () => {
  const { file } = await sandbox();
  await chmod(file, 0o644);
  assert.match((await checkTrustedFile(file, { trustedUids: me, executable: true })).reason, /not executable/);
});

test('a symlink is judged by, and resolves to, its target', async () => {
  const { dir, file } = await sandbox();
  await chmod(file, 0o777);
  const link = join(dir, 'link');
  await symlink(file, link);
  const result = await checkTrustedFile(link, { trustedUids: me });
  assert.equal(result.ok, false);
  assert.match(result.reason, new RegExp(file));
});

test('a missing file is refused with its error code', async () => {
  const result = await checkTrustedFile('/nonexistent/cb', { trustedUids: me });
  assert.equal(result.ok, false);
  assert.equal(result.code, 'ENOENT');
});
