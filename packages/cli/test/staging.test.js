import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, stat, chmod, mkdir, readdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { stagingDir } from '../src/staging.js';

test('creates a private per-target directory under XDG_CACHE_HOME', async () => {
  const cache = await mkdtemp(join(tmpdir(), 'cb-cache-'));
  const dir = await stagingDir({ env: { XDG_CACHE_HOME: cache }, home: '/nonexistent', version: '0.4.7', arch: 'amd64', uid: process.getuid() });
  assert.equal(dir, join(cache, 'circuitbreaker', 'staging', '0.4.7-amd64'));
  assert.equal((await stat(dir)).mode & 0o777, 0o700);
});

test('falls back to ~/.cache', async () => {
  const home = await mkdtemp(join(tmpdir(), 'cb-home-'));
  const dir = await stagingDir({ env: {}, home, version: '0.4.7', arch: 'arm64', uid: process.getuid() });
  assert.equal(dir, join(home, '.cache', 'circuitbreaker', 'staging', '0.4.7-arm64'));
});

test('refuses a version or arch that would name anything but one directory under staging', async () => {
  const root = await mkdtemp(join(tmpdir(), 'cb-cache-'));
  const cache = join(root, 'cache');
  for (const [version, arch] of [['0.4.8/../../../../escaped', 'amd64'], ['..', 'amd64'], ['0.4.8', '../x'], ['', 'amd64'], ['0.4.8', '']]) {
    await assert.rejects(stagingDir({ env: { XDG_CACHE_HOME: cache }, home: '/x', version, arch, uid: process.getuid() }), { code: 'PREFLIGHT' }, `${version} ${arch}`);
  }
  assert.deepEqual(await readdir(root), [], 'nothing was created, inside the cache or beside it');
});

test('refuses a group/world-accessible or foreign-owned staging directory', async () => {
  const cache = await mkdtemp(join(tmpdir(), 'cb-cache-'));
  const dir = join(cache, 'circuitbreaker', 'staging', '0.4.7-amd64');
  await mkdir(dir, { recursive: true });
  await chmod(dir, 0o755);
  await assert.rejects(stagingDir({ env: { XDG_CACHE_HOME: cache }, home: '/x', version: '0.4.7', arch: 'amd64', uid: process.getuid() }), { code: 'PREFLIGHT' });
  await chmod(dir, 0o700);
  await assert.rejects(stagingDir({ env: { XDG_CACHE_HOME: cache }, home: '/x', version: '0.4.7', arch: 'amd64', uid: process.getuid() + 1 }), { code: 'PREFLIGHT' });
});
