import { test } from 'node:test';
import assert from 'node:assert/strict';
import { generateKeyPairSync, sign, createHash } from 'node:crypto';
import { mkdtemp, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { verifyBundle } from '../src/bundle-verify.js';
import { parseTrustedKeys } from '../src/release-trust.js';
import { makeTarGz } from './helpers/tar.js';

const NAME = 'circuit-breaker_0.4.7_linux_amd64.tar.gz';

// SHA256SUMS lists `name`; the tarball is written as `fileName` (defaults to
// `name`), so a renamed copy of a genuine bundle can be modelled.
async function fixture({
  signed = true, trusted = true, name = NAME, fileName = name, tamper = false, version = '0.4.7',
  explicitVersion = false, entries = [{ name: 'bin/circuit-breaker', data: Buffer.from('x') }], sig,
} = {}) {
  const dir = await mkdtemp(join(tmpdir(), 'cb-vb-'));
  const tarball = makeTarGz(entries);
  await writeFile(join(dir, fileName), tarball);
  const sha256 = createHash('sha256').update(tarball).digest('hex');
  const sums = Buffer.from(`${sha256}  ./${name}\n`);
  await writeFile(join(dir, 'SHA256SUMS'), sums);
  const { publicKey, privateKey } = generateKeyPairSync('ed25519');
  const raw = publicKey.export({ format: 'der', type: 'spki' }).subarray(-32);
  const id = createHash('sha256').update(raw).digest('hex').slice(0, 16);
  const other = generateKeyPairSync('ed25519');
  if (signed) await writeFile(join(dir, 'SHA256SUMS.sig'), sig ?? sign(null, sums, trusted ? privateKey : other.privateKey).toString('base64'));
  if (tamper) await writeFile(join(dir, fileName), Buffer.concat([tarball, Buffer.from('x')]));
  const calls = [];
  return {
    id, sha256, calls,
    args: (over = {}) => ({
      tarballPath: join(dir, fileName), sumsPath: join(dir, 'SHA256SUMS'), sigPath: signed ? join(dir, 'SHA256SUMS.sig') : null,
      origin: 'download', target: { version, explicitVersion }, airgap: false,
      keys: parseTrustedKeys(`${id} ${raw.toString('base64')} 0.4.7 t`),
      attest: async (digest) => { calls.push(digest); return { ok: true }; },
      ...over,
    }),
  };
}

test('signed, hashed, attested and safe passes in that order', async () => {
  const f = await fixture();
  const r = await verifyBundle(f.args());
  assert.equal(r.ok, true, r.reason);
  assert.equal(r.sha256, f.sha256);
  assert.deepEqual(r.signature, { keyId: f.id });
  assert.equal(r.provenance, 'verified');
  assert.deepEqual(r.archive, { entries: 1, totalBytes: 1 });
  assert.deepEqual(f.calls, [f.sha256]);
});

test('an untrusted signature fails before the hash or provenance are consulted', async () => {
  const f = await fixture({ trusted: false, tamper: true });
  const r = await verifyBundle(f.args());
  assert.equal(r.ok, false);
  assert.equal(r.code, 'TRUST');
  assert.match(r.reason, new RegExp(`does not verify.*Keys tried: ${f.id}$`));
  assert.deepEqual(f.calls, []);
});

test('no trusted keys and an unreadable signature are trust failures', async () => {
  const f = await fixture();
  assert.match((await verifyBundle(f.args({ keys: [] }))).reason, /trusts no release keys/);
  const g = await fixture({ sig: 'not base64 !!' });
  const r = await verifyBundle(g.args());
  assert.equal(r.code, 'TRUST');
  assert.match(r.reason, /SHA256SUMS\.sig is unreadable/);
  assert.deepEqual(g.calls, []);
});

test('a tampered tarball fails at the hash', async () => {
  const f = await fixture({ tamper: true });
  const r = await verifyBundle(f.args());
  assert.equal(r.code, 'TRUST');
  assert.match(r.reason, /SHA256 mismatch/);
  assert.deepEqual(f.calls, []);
});

test('missing provenance online fails; air-gap skips it without calling attest', async () => {
  const f = await fixture();
  const refused = await verifyBundle(f.args({ attest: async () => ({ ok: false, reason: 'none' }) }));
  assert.equal(refused.code, 'TRUST');
  assert.match(refused.reason, /build provenance could not be verified \(none\)/);
  const g = await fixture();
  const r = await verifyBundle(g.args({ airgap: true }));
  assert.equal(r.ok, true, r.reason);
  assert.equal(r.provenance, 'skipped-airgap');
  assert.deepEqual(g.calls, []);
});

test('a network failure while checking provenance propagates as an error, not a verdict', async () => {
  const f = await fixture();
  const failure = Object.assign(new Error('could not reach api.github.com'), { code: 'NETWORK' });
  await assert.rejects(verifyBundle(f.args({ attest: async () => { throw failure; } })), failure);
});

test('unsigned is refused unless explicitly older and canonical', async () => {
  const latest = await fixture({ signed: false });
  assert.match((await verifyBundle(latest.args())).reason, /release v0\.4\.7 publishes no SHA256SUMS\.sig; every release from v0\.4\.7 on is signed/);
  const old = await fixture({ signed: false, version: '0.4.3', explicitVersion: true, name: 'circuit-breaker_0.4.3_linux_amd64.tar.gz' });
  const r = await verifyBundle(old.args());
  assert.equal(r.ok, true, r.reason);
  assert.deepEqual(r.signature, { unsigned: 'explicit-older' });
  assert.equal(r.provenance, 'not-applicable');
  assert.deepEqual(old.calls, []);
  const sneaky = await fixture({ signed: false, version: '0.4.3', explicitVersion: false, name: 'circuit-breaker_0.4.3_linux_amd64.tar.gz' });
  assert.equal((await verifyBundle(sneaky.args())).ok, false);
  const prerelease = await fixture({ signed: false, version: '0.4.3-rc.1', explicitVersion: true, name: 'circuit-breaker_0.4.3-rc.1_linux_amd64.tar.gz' });
  assert.equal((await verifyBundle(prerelease.args())).ok, false, 'non-canonical versions always need a signature');
});

test('a hash-mismatched bundle wearing a pinned v0.4.6 name is refused unsigned', async () => {
  const f = await fixture({ signed: false, version: '0.4.6', name: 'circuit-breaker_0.4.6_linux_amd64.tar.gz' });
  const r = await verifyBundle(f.args());
  assert.equal(r.code, 'TRUST');
  assert.match(r.reason, /publishes no SHA256SUMS\.sig/);
});

test('a local bundle without a signature is told to bring one', async () => {
  const f = await fixture({ signed: false });
  const r = await verifyBundle(f.args({ origin: 'local', target: { version: '0.4.7', explicitVersion: false } }));
  assert.equal(r.code, 'TRUST');
  assert.match(r.reason, /no SHA256SUMS\.sig next to circuit-breaker_0\.4\.7_linux_amd64\.tar\.gz/);
});

test('a renamed bundle is not listed', async () => {
  const f = await fixture({ fileName: `${NAME.slice(0, -7)}(1).tar.gz` });
  const r = await verifyBundle(f.args());
  assert.equal(r.code, 'TRUST');
  assert.match(r.reason, /not listed in SHA256SUMS/);
  assert.deepEqual(f.calls, []);
});

test('no SHA256SUMS fails', async () => {
  const f = await fixture();
  assert.match((await verifyBundle(f.args({ sumsPath: null }))).reason, /no SHA256SUMS/);
  const local = await verifyBundle(f.args({ sumsPath: null, origin: 'local' }));
  assert.match(local.reason, /no SHA256SUMS next to/);
});

test('an unsafe archive fails after provenance, with the scan reason', async () => {
  const f = await fixture({ entries: [{ name: '../escape', data: Buffer.from('x') }] });
  const r = await verifyBundle(f.args());
  assert.equal(r.code, 'TRUST');
  assert.match(r.reason, /^unsafe bundle archive: .*'\.\.' segment/);
  assert.deepEqual(f.calls, [f.sha256]);
});
