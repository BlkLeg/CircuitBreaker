import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { execFileSync } from 'node:child_process';
import { checkArchive } from '../src/archive-check.js';
import { makeTarGz } from './helpers/tar.js';

async function write(entries) {
  const path = join(await mkdtemp(join(tmpdir(), 'cb-tar-')), 'b.tar.gz');
  await writeFile(path, makeTarGz(entries));
  return path;
}

test('a normal bundle with relative in-tree symlinks passes', async () => {
  const p = await write([
    { name: 'bin/', type: '5' },
    { name: 'bin/circuit-breaker', data: Buffer.from('#!/bin/sh\n') },
    { name: 'python/bin/python3', type: '2', linkname: 'python3.12' },
    { name: 'python/lib/link', type: '2', linkname: '../bin/python3' },
    { name: './share/VERSION', data: Buffer.from('0.4.7\n') },
  ]);
  const r = await checkArchive(p);
  assert.equal(r.ok, true, r.reason);
  assert.equal(r.entries, 5);
});

for (const [label, entry, needle] of [
  ['absolute path', { name: '/etc/passwd', data: Buffer.from('x') }, 'absolute'],
  ['parent traversal', { name: 'a/../../etc/passwd', data: Buffer.from('x') }, 'outside'],
  ['absolute symlink', { name: 'evil', type: '2', linkname: '/etc/shadow' }, 'symlink'],
  ['escaping symlink', { name: 'a/evil', type: '2', linkname: '../../etc' }, 'symlink'],
  ['escaping hardlink', { name: 'evil', type: '1', linkname: '../outside' }, 'hardlink'],
  ['device node', { name: 'dev/sda', type: '3' }, 'type'],
]) {
  test(`refuses ${label}`, async () => {
    const r = await checkArchive(await write([{ name: 'ok', data: Buffer.from('x') }, entry]));
    assert.equal(r.ok, false);
    assert.match(r.reason, new RegExp(needle));
  });
}

test('refuses archives over the entry or size budget', async () => {
  const p = await write([{ name: 'a', data: Buffer.alloc(2000) }, { name: 'b', data: Buffer.from('x') }]);
  assert.match((await checkArchive(p, { maxEntries: 1, maxTotalBytes: 1e9 })).reason, /entries/);
  assert.match((await checkArchive(p, { maxEntries: 10, maxTotalBytes: 1000 })).reason, /bytes/);
});

test('a corrupt header checksum or truncated gzip is refused, not thrown', async () => {
  const good = makeTarGz([{ name: 'a', data: Buffer.from('x') }]);
  const dir = await mkdtemp(join(tmpdir(), 'cb-tar-'));
  await writeFile(join(dir, 't.tar.gz'), good.subarray(0, good.length - 10));
  assert.equal((await checkArchive(join(dir, 't.tar.gz'))).ok, false);
});

test('GNU tar output (long names, pax headers) is understood', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'cb-gnu-'));
  const long = 'd'.repeat(120);
  execFileSync('mkdir', ['-p', join(dir, 'src', long)]);
  execFileSync('sh', ['-c', `printf x > "${join(dir, 'src', long, 'f')}" && ln -s f "${join(dir, 'src', long, 'l')}"`]);
  execFileSync('tar', ['-czf', join(dir, 'g.tar.gz'), '-C', join(dir, 'src'), '.']);
  const r = await checkArchive(join(dir, 'g.tar.gz'));
  assert.equal(r.ok, true, r.reason);
});
