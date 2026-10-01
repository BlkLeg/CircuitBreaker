import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';
import { mkdtemp, readdir, readFile, symlink, writeFile, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { downloadAsset, discardAsset } from '../src/release-download.js';

const BODY = Buffer.from('0123456789abcdef'.repeat(64)); // 1024 bytes
const asset = { id: 7, name: 'bundle.tar.gz', size: BODY.length, url: 'https://dl/bundle.tar.gz' };
const roomy = async () => ({ bavail: 1e9, bsize: 4096 });
const noSleep = async () => {};

function server({ failFirst = 0, status = 200, body = BODY, honourRange = true, contentRangeFor } = {}) {
  const calls = [];
  let failures = failFirst;
  const fetchImpl = async (url, init) => {
    calls.push({ url, range: init.headers.range ?? null });
    if (failures > 0) { failures -= 1; throw new TypeError('fetch failed'); }
    if (status !== 200) return new Response('x', { status });
    const m = /bytes=(\d+)-/.exec(init.headers.range ?? '');
    if (m && honourRange) {
      const from = Number(m[1]);
      const contentRange = contentRangeFor ? contentRangeFor(from) : `bytes ${from}-${body.length - 1}/${body.length}`;
      const headers = contentRange === null ? {} : { 'content-range': contentRange };
      return new Response(body.subarray(from), { status: 206, headers });
    }
    return new Response(body, { status: 200 });
  };
  return { fetchImpl, calls };
}

async function dir() { return mkdtemp(join(tmpdir(), 'cb-dl-')); }

test('downloads to .part then renames, recording the asset identity', async () => {
  const d = await dir();
  const s = server();
  const path = await downloadAsset(asset, d, { fetchImpl: s.fetchImpl, statfs: roomy, sleep: noSleep });
  assert.equal(path, join(d, 'bundle.tar.gz'));
  assert.deepEqual(await readFile(path), BODY);
  assert.deepEqual(JSON.parse(await readFile(join(d, 'bundle.tar.gz.asset.json'), 'utf8')), { id: 7, size: 1024, url: asset.url });
});

test('retries transport failures up to three times, then gives up as a network error', async () => {
  const d = await dir();
  const ok = server({ failFirst: 3 });
  await downloadAsset(asset, d, { fetchImpl: ok.fetchImpl, statfs: roomy, sleep: noSleep });
  assert.equal(ok.calls.length, 4);
  const bad = server({ failFirst: 4 });
  await assert.rejects(downloadAsset(asset, await dir(), { fetchImpl: bad.fetchImpl, statfs: roomy, sleep: noSleep }), { code: 'NETWORK' });
});

test('does not retry a 404', async () => {
  const s = server({ status: 404 });
  await assert.rejects(downloadAsset(asset, await dir(), { fetchImpl: s.fetchImpl, statfs: roomy, sleep: noSleep }), { code: 'HTTP_STATUS' });
  assert.equal(s.calls.length, 1);
});

test('resumes a .part only when the recorded identity matches', async () => {
  const d = await dir();
  await writeFile(join(d, 'bundle.tar.gz.part'), BODY.subarray(0, 300));
  await writeFile(join(d, 'bundle.tar.gz.asset.json'), JSON.stringify({ id: 7, size: 1024, url: asset.url }));
  const s = server();
  await downloadAsset(asset, d, { fetchImpl: s.fetchImpl, statfs: roomy, sleep: noSleep });
  assert.equal(s.calls[0].range, 'bytes=300-');
  assert.deepEqual(await readFile(join(d, 'bundle.tar.gz')), BODY);

  const d2 = await dir();
  await writeFile(join(d2, 'bundle.tar.gz.part'), Buffer.from('stale bytes from another asset'));
  await writeFile(join(d2, 'bundle.tar.gz.asset.json'), JSON.stringify({ id: 6, size: 1024, url: asset.url }));
  const s2 = server();
  await downloadAsset(asset, d2, { fetchImpl: s2.fetchImpl, statfs: roomy, sleep: noSleep });
  assert.equal(s2.calls[0].range, null);
  assert.deepEqual(await readFile(join(d2, 'bundle.tar.gz')), BODY);
});

test('a server that ignores Range restarts cleanly instead of appending', async () => {
  const d = await dir();
  await writeFile(join(d, 'bundle.tar.gz.part'), BODY.subarray(0, 300));
  await writeFile(join(d, 'bundle.tar.gz.asset.json'), JSON.stringify({ id: 7, size: 1024, url: asset.url }));
  const s = server({ honourRange: false });
  await downloadAsset(asset, d, { fetchImpl: s.fetchImpl, statfs: roomy, sleep: noSleep });
  assert.deepEqual(await readFile(join(d, 'bundle.tar.gz')), BODY);
});

test('more bytes than declared, or fewer, is refused and leaves no final file', async () => {
  const d = await dir();
  const big = server({ body: Buffer.concat([BODY, Buffer.from('extra')]) });
  await assert.rejects(downloadAsset(asset, d, { fetchImpl: big.fetchImpl, statfs: roomy, sleep: noSleep }), { code: 'NETWORK' });
  await assert.rejects(stat(join(d, 'bundle.tar.gz')), { code: 'ENOENT' });
  const short = server({ body: BODY.subarray(0, 10) });
  await assert.rejects(downloadAsset(asset, await dir(), { fetchImpl: short.fetchImpl, statfs: roomy, sleep: noSleep, retries: 0 }), { code: 'NETWORK' });
});

test('insufficient disk space is a preflight failure before any request', async () => {
  const s = server();
  const tight = async () => ({ bavail: 1, bsize: 4096 });
  await assert.rejects(downloadAsset(asset, await dir(), { fetchImpl: s.fetchImpl, statfs: tight, sleep: noSleep }), { code: 'PREFLIGHT' });
  assert.equal(s.calls.length, 0);
});

test('an existing complete file with matching identity is reused without a request', async () => {
  const d = await dir();
  await writeFile(join(d, 'bundle.tar.gz'), BODY);
  await writeFile(join(d, 'bundle.tar.gz.asset.json'), JSON.stringify({ id: 7, size: 1024, url: asset.url }));
  const s = server();
  await downloadAsset(asset, d, { fetchImpl: s.fetchImpl, statfs: roomy, sleep: noSleep });
  assert.equal(s.calls.length, 0);
});

test('a body that stalls after some bytes is aborted, retried with Range, and completes', async () => {
  const d = await dir();
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push(init.headers.range ?? null);
    const m = /bytes=(\d+)-/.exec(init.headers.range ?? '');
    if (m) return new Response(BODY.subarray(Number(m[1])), { status: 206, headers: { 'content-range': `bytes ${m[1]}-1023/1024` } });
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(new Uint8Array(BODY.subarray(0, 300)));
        init.signal.addEventListener('abort', () => controller.error(init.signal.reason), { once: true });
      },
    });
    return new Response(stream, { status: 200 });
  };
  const path = await downloadAsset(asset, d, { fetchImpl, statfs: roomy, sleep: noSleep, timeoutMs: 50 });
  assert.deepEqual(calls, [null, 'bytes=300-']);
  assert.deepEqual(await readFile(path), BODY);
});

test('an invalid declared size is refused before any request', async () => {
  const s = server();
  for (const size of [0, -1, 1.5, NaN, '1024', undefined, Number.MAX_SAFE_INTEGER + 1]) {
    await assert.rejects(downloadAsset({ ...asset, size }, await dir(), { fetchImpl: s.fetchImpl, statfs: roomy, sleep: noSleep }), { code: 'NETWORK' });
  }
  assert.equal(s.calls.length, 0);
});

for (const [label, contentRangeFor] of [
  ['wrong start', (from) => `bytes ${from + 5}-1023/1024`],
  ['missing header', () => null],
  ['mismatched total', (from) => `bytes ${from}-1023/2048`],
]) {
  test(`a 206 with ${label} in Content-Range is discarded and the download restarts from zero`, async () => {
    const d = await dir();
    await writeFile(join(d, 'bundle.tar.gz.part'), BODY.subarray(0, 300));
    await writeFile(join(d, 'bundle.tar.gz.asset.json'), JSON.stringify({ id: 7, size: 1024, url: asset.url }));
    // First resumed answer carries wrong bytes (a mixed file would be 1024 long); later ones are honest.
    const calls = [];
    const fetchImpl = async (url, init) => {
      calls.push(init.headers.range ?? null);
      if (calls.length === 1) {
        const headers = contentRangeFor(300) === null ? {} : { 'content-range': contentRangeFor(300) };
        return new Response(Buffer.from('Z'.repeat(724)), { status: 206, headers });
      }
      return new Response(BODY, { status: 200 });
    };
    const path = await downloadAsset(asset, d, { fetchImpl, statfs: roomy, sleep: noSleep });
    assert.deepEqual(calls, ['bytes=300-', null]);
    assert.deepEqual(await readFile(path), BODY);
  });
}

test('a full disk while writing is a preflight failure, not a retried network error', async (t) => {
  if (!existsSync('/dev/full')) {
    t.skip('needs /dev/full, which answers every write with ENOSPC (Linux)');
    return;
  }
  const d = await dir();
  await writeFile(join(d, 'bundle.tar.gz.asset.json'), JSON.stringify({ id: 7, size: 1024, url: asset.url }));
  await symlink('/dev/full', join(d, 'bundle.tar.gz.part'));
  const s = server();
  await assert.rejects(downloadAsset(asset, d, { fetchImpl: s.fetchImpl, statfs: roomy, sleep: noSleep }),
    (e) => e.code === 'PREFLIGHT' && /no space left/.test(e.message) && e.message.includes(d));
  assert.equal(s.calls.length, 1);
});

test('the disk-space check runs before anything is written to staging', async () => {
  const d = await dir();
  const tight = async () => ({ bavail: 1, bsize: 4096 });
  await assert.rejects(downloadAsset(asset, d, { fetchImpl: server().fetchImpl, statfs: tight, sleep: noSleep }), { code: 'PREFLIGHT' });
  assert.deepEqual(await readdir(d), []);
});

test('discardAsset removes the staged file, its .part and its identity record', async () => {
  const d = await dir();
  for (const suffix of ['', '.part', '.asset.json']) await writeFile(join(d, `bundle.tar.gz${suffix}`), 'x');
  await writeFile(join(d, 'SHA256SUMS'), 'kept');
  await discardAsset(asset, d);
  assert.deepEqual(await readdir(d), ['SHA256SUMS']);
  await discardAsset(asset, d);
});
