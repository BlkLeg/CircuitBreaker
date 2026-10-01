import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { execFileSync } from 'node:child_process';
import { gunzipSync, gzipSync } from 'node:zlib';
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

function pax(records) {
  const parts = Object.entries(records).map(([k, v]) => {
    const body = Buffer.from(` ${k}=${v}\n`, 'utf8');
    let len = body.length + 1;
    while (String(len).length + body.length !== len) len = String(len).length + body.length;
    return Buffer.concat([Buffer.from(String(len)), body]);
  });
  return Buffer.concat(parts);
}

const refused = async (entries) => checkArchive(await write(entries));

test('refuses a chained symlink escape via a dot link and a .. file name', async () => {
  const r = await refused([
    { name: 'd/l', type: '2', linkname: '.' },
    { name: 'd/l/../../x', data: Buffer.from('x') },
  ]);
  assert.equal(r.ok, false);
});

test('refuses a chained symlink escape through a link to a symlinked parent', async () => {
  const r = await refused([
    { name: 'a/s', type: '2', linkname: '..' },
    { name: 'esc', type: '2', linkname: 'a/s/..' },
    { name: 'esc/pwn', data: Buffer.from('x') },
  ]);
  assert.equal(r.ok, false);
  assert.match(r.reason, /symlink/);
});

test('refuses .//../x, which a single ./ strip would let through', async () => {
  const r = await refused([{ name: './/../x', data: Buffer.from('x') }]);
  assert.equal(r.ok, false);
  assert.match(r.reason, /outside/);
});

for (const order of ['link first', 'file first']) {
  test(`refuses an entry written through an in-archive symlink (${order})`, async () => {
    const link = { name: 'lnk', type: '2', linkname: 'sub' };
    const file = { name: 'lnk/evil', data: Buffer.from('x') };
    const r = await refused(order === 'link first' ? [link, file] : [file, link]);
    assert.equal(r.ok, false);
    assert.match(r.reason, /through symlink lnk/);
  });
}

test('honours a pax size override instead of skipping hidden headers', async () => {
  const hidden = gunzipSync(makeTarGz([{ name: '/etc/evil', data: Buffer.alloc(0) }])).subarray(0, 512);
  const r = await refused([
    { name: 'pax', type: 'x', data: pax({ size: '0' }) },
    { name: 'a', data: hidden },
  ]);
  assert.equal(r.ok, false);
  assert.match(r.reason, /absolute/);
});

test('parses non-ASCII pax paths by byte length', async () => {
  const ok = await refused([
    { name: 'pax', type: 'x', data: pax({ path: 'ünï/çödé.txt' }) },
    { name: 'short', data: Buffer.from('x') },
  ]);
  assert.equal(ok.ok, true, ok.reason);
  const bad = await refused([
    { name: 'pax', type: 'x', data: pax({ path: 'ü/../../x' }) },
    { name: 'short', data: Buffer.from('x') },
  ]);
  assert.equal(bad.ok, false);
  assert.match(bad.reason, /outside/);
});

test('a malformed pax record is refused', async () => {
  const r = await refused([
    { name: 'pax', type: 'x', data: Buffer.from('99 path=x\n') },
    { name: 'a', data: Buffer.from('x') },
  ]);
  assert.equal(r.ok, false);
  assert.match(r.reason, /pax/);
});

test('a flipped header byte is a checksum failure', async () => {
  const raw = gunzipSync(makeTarGz([{ name: 'abc', data: Buffer.from('x') }]));
  raw[1] ^= 0x01;
  const dir = await mkdtemp(join(tmpdir(), 'cb-tar-'));
  await writeFile(join(dir, 'c.tar.gz'), gzipSync(raw));
  const r = await checkArchive(join(dir, 'c.tar.gz'));
  assert.equal(r.ok, false);
  assert.match(r.reason, /checksum/);
});
