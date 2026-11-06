import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { chmod, mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import net from 'node:net';
import {
  verifyAttestation, defaultCreateVerifier, sigstoreCacheDir,
  ATTESTATION_API, ATTESTATION_IDENTITY, ATTESTATION_IDENTITY_PATTERN, ATTESTATION_ISSUER,
  BUNDLE_MAX_BYTES, SIGSTORE_RETRY, SIGSTORE_TIMEOUT_MS,
} from '../src/attestation.js';
import { NetworkError, HttpStatusError } from '../src/http.js';

const require = createRequire(import.meta.url);
const DIGEST = 'a'.repeat(64);
const CACHE = '/cache/circuitbreaker/sigstore';
const bundleFor = (digest) => ({
  dsseEnvelope: { payload: Buffer.from(JSON.stringify({ subject: [{ name: 'x', digest: { sha256: digest } }] })).toString('base64') },
});
const api = (attestations, digest = DIGEST) => async (url) => {
  assert.equal(url, `${ATTESTATION_API}/sha256:${digest}`);
  return { attestations };
};
const inline = (bundles) => api(bundles.map((bundle) => ({ bundle })));
// A verifier factory standing in for sigstore: `accepts(bundle)` decides each bundle.
const verifierThat = (accepts) => async () => async (bundle) => accepts(bundle);
const run = (overrides) => verifyAttestation({ sha256: DIGEST, tufCachePath: CACHE, createVerifier: verifierThat(() => true), ...overrides });

// Encodes bytes as a valid snappy block made of literals only.
function snappyLiterals(data) {
  const parts = [];
  let n = data.length;
  const varint = [];
  do { varint.push((n & 0x7f) | (n > 0x7f ? 0x80 : 0)); n >>>= 7; } while (n > 0);
  parts.push(Buffer.from(varint));
  for (let at = 0; at < data.length; at += 65536) {
    const chunk = data.subarray(at, at + 65536);
    parts.push(Buffer.from([61 << 2, (chunk.length - 1) & 0xff, (chunk.length - 1) >> 8]), chunk);
  }
  return Buffer.concat(parts);
}
const compressed = (bundle) => snappyLiterals(Buffer.from(JSON.stringify(bundle)));

test('passes the pinned issuer, the anchored workflow identity and the TUF bounds to sigstore', async () => {
  let options;
  const createVerifier = async (opts) => { options = opts; return async () => true; };
  assert.deepEqual(await run({ fetchJson: inline([bundleFor(DIGEST)]), createVerifier }), { ok: true });
  assert.deepEqual(options, {
    certificateIssuer: ATTESTATION_ISSUER,
    certificateIdentityURI: ATTESTATION_IDENTITY_PATTERN,
    tufCachePath: CACHE,
    timeout: SIGSTORE_TIMEOUT_MS,
    retry: SIGSTORE_RETRY,
  });
  assert.equal(ATTESTATION_IDENTITY, 'https://github.com/BlkLeg/CircuitBreaker/.github/workflows/release.yml@refs/heads/main');
  assert.equal(ATTESTATION_ISSUER, 'https://token.actions.githubusercontent.com');
});

test("the identity pin is exact under sigstore's own regex matcher", () => {
  // sigstore 5 treats certificateIdentityURI as an unanchored RegExp.
  const { verifySubjectAlternativeName } = require('@sigstore/verify/dist/policy.js');
  const base = 'https://github.com/BlkLeg/CircuitBreaker/.github/workflows/release';
  assert.doesNotThrow(() => verifySubjectAlternativeName(ATTESTATION_IDENTITY_PATTERN, ATTESTATION_IDENTITY));
  for (const lookalike of [
    `${base}.yml@refs/heads/main-evil`,
    `${base}.yml@refs/heads/mainline`,
    `${base}.yml@refs/heads/main/x`,
    `${base}Xyml@refs/heads/main`,
    `https://evil.example/${base}.yml@refs/heads/main`,
  ]) {
    assert.throws(() => verifySubjectAlternativeName(ATTESTATION_IDENTITY_PATTERN, lookalike), { name: 'PolicyError' }, lookalike);
    // The bare URL, as first shipped, accepted every one of these.
    assert.doesNotThrow(() => verifySubjectAlternativeName(ATTESTATION_IDENTITY, lookalike), lookalike);
  }
});

test('a bundle sigstore rejects, or one attesting another digest, does not count', async () => {
  const reject = verifierThat(() => false);
  assert.deepEqual(await run({ fetchJson: inline([bundleFor(DIGEST)]), createVerifier: reject }), { ok: false, reason: 'unverified' });
  assert.deepEqual(await run({ fetchJson: inline([bundleFor('b'.repeat(64))]) }), { ok: false, reason: 'unverified' });
});

test('one verified bundle for the digest is enough among rejected ones', async () => {
  const good = bundleFor(DIGEST);
  const bundles = [bundleFor(DIGEST), { dsseEnvelope: { payload: 'not json' } }, good];
  assert.deepEqual(await run({ fetchJson: inline(bundles), createVerifier: verifierThat((b) => b === good) }), { ok: true });
});

test('a verified bundle whose payload is not a statement does not count', async () => {
  const garbled = { dsseEnvelope: { payload: Buffer.from('not json').toString('base64') } };
  assert.deepEqual(await run({ fetchJson: inline([garbled]) }), { ok: false, reason: 'unverified' });
});

test('no attestation at all is its own result, and sigstore is never loaded for it', async () => {
  const createVerifier = async () => { throw new Error('must not be called'); };
  assert.deepEqual(await run({ fetchJson: inline([]), createVerifier }), { ok: false, reason: 'none' });
  assert.deepEqual(await run({ fetchJson: api([{ bundle: null }, { bundle_url: null }]), createVerifier }), { ok: false, reason: 'none' });
  const notFound = async () => { throw new HttpStatusError('https://x', 404); };
  assert.deepEqual(await run({ fetchJson: notFound, createVerifier }), { ok: false, reason: 'none' });
});

test('any other fetch failure propagates to the caller', async () => {
  const unavailable = async () => { throw new HttpStatusError('https://x', 503); };
  await assert.rejects(run({ fetchJson: unavailable }), /503/);
});

test('sigstore is set up once, however many bundles there are', async () => {
  let created = 0;
  let checked = 0;
  const createVerifier = async () => { created += 1; return async () => { checked += 1; return false; }; };
  await run({ fetchJson: inline([bundleFor(DIGEST), bundleFor(DIGEST), bundleFor(DIGEST)]), createVerifier });
  assert.equal(created, 1);
  assert.equal(checked, 3);
});

test('a failure setting sigstore up propagates instead of reading as unverified', async () => {
  const createVerifier = async () => { throw new NetworkError("could not load sigstore's trusted root"); };
  await assert.rejects(run({ fetchJson: inline([bundleFor(DIGEST)]), createVerifier }), (e) => e instanceof NetworkError);
});

test('an error from the verifier that is not a rejection propagates', async () => {
  const createVerifier = async () => async () => { throw new TypeError('boom'); };
  await assert.rejects(run({ fetchJson: inline([bundleFor(DIGEST)]), createVerifier }), TypeError);
});

test("follows bundle_url when the API leaves bundle null, as GitHub's does", async () => {
  const url = 'https://tmaproduction.blob.core.windows.net/attestations/1/x.json?sig=abc';
  const calls = [];
  const fetchBytes = async (u, options) => { calls.push([u, options]); return compressed(bundleFor(DIGEST)); };
  const fetchJson = api([{ repository_id: 1, bundle_url: url, initiator: 'user', bundle: null }]);
  assert.deepEqual(await run({ fetchJson, fetchBytes }), { ok: true });
  assert.deepEqual(calls, [[url, { maxBytes: BUNDLE_MAX_BYTES }]]);
});

test('a real GitHub attestation answer verifies through its bundle_url', async () => {
  // cli/cli's SLSA build provenance for gh_2.102.0_linux_amd64.tar.gz, as the live API answered it.
  const sha256 = 'bb766f710eef8ede859c18578c72c327597cd4c8a85b06001b1f3843c6019386';
  const blob = await readFile(new URL('./fixtures/gh-slsa-provenance.snappy', import.meta.url));
  const seen = [];
  const result = await verifyAttestation({
    sha256,
    tufCachePath: CACHE,
    fetchJson: api([{ repository_id: 212613049, bundle_url: 'https://tmaproduction.blob.core.windows.net/a', initiator: 'user', bundle: null }], sha256),
    fetchBytes: async () => blob,
    createVerifier: verifierThat((bundle) => { seen.push(bundle.mediaType); return true; }),
  });
  assert.deepEqual(result, { ok: true });
  assert.deepEqual(seen, ['application/vnd.dev.sigstore.bundle.v0.3+json']);
});

test('a corrupt bundle_url body does not count, but does not hide a good bundle', async () => {
  const corrupt = async () => Buffer.from([0x05, 0x10, 0x68]);
  const notJson = async () => snappyLiterals(Buffer.from('not json'));
  for (const fetchBytes of [corrupt, notJson]) {
    assert.deepEqual(await run({ fetchJson: api([{ bundle: null, bundle_url: 'https://blob/a' }]), fetchBytes }), { ok: false, reason: 'unverified' });
    const mixed = api([{ bundle: null, bundle_url: 'https://blob/a' }, { bundle: bundleFor(DIGEST) }]);
    assert.deepEqual(await run({ fetchJson: mixed, fetchBytes }), { ok: true });
  }
});

test('inline and bundle_url entries mix, each checked by sigstore', async () => {
  const rejected = bundleFor(DIGEST);
  const fetched = [];
  const fetchBytes = async (u) => { fetched.push(u); return compressed(bundleFor(DIGEST)); };
  const fetchJson = api([{ bundle: rejected }, { bundle: null, bundle_url: 'https://blob/b' }]);
  assert.deepEqual(await run({ fetchJson, fetchBytes, createVerifier: verifierThat((b) => b !== rejected) }), { ok: true });
  assert.deepEqual(fetched, ['https://blob/b']);
});

test('a failed bundle_url download is a network error, not a missing attestation', async () => {
  const fetchJson = api([{ bundle: null, bundle_url: 'https://blob/a' }]);
  await assert.rejects(run({ fetchJson, fetchBytes: async () => { throw new NetworkError('could not reach blob'); } }), NetworkError);
  await assert.rejects(run({ fetchJson, fetchBytes: async () => { throw new HttpStatusError('https://blob/a', 403); } }), HttpStatusError);
});

test('a bundle_url that is not https is never fetched', async () => {
  const fetchBytes = async () => { throw new Error('must not be fetched'); };
  assert.deepEqual(await run({ fetchJson: api([{ bundle: null, bundle_url: 'http://blob/a' }]), fetchBytes }), { ok: false, reason: 'unverified' });
});

test('the TUF cache lives under the CLI cache directory', () => {
  assert.equal(sigstoreCacheDir({ env: { XDG_CACHE_HOME: '/x' }, home: '/h' }), '/x/circuitbreaker/sigstore');
  assert.equal(sigstoreCacheDir({ env: {}, home: '/h' }), '/h/.cache/circuitbreaker/sigstore');
});

// sigstore's real error classes, behind a fake createVerifier.
async function fakeSigstore({ createError, verifyError }) {
  const real = await import('sigstore');
  return async () => ({
    TUFError: real.TUFError,
    VerificationError: real.VerificationError,
    PolicyError: real.PolicyError,
    ValidationError: real.ValidationError,
    createVerifier: async () => {
      if (createError) throw createError;
      return { verify: () => { if (verifyError) throw verifyError; } };
    },
  });
}

test("the default verifier counts only sigstore's verification errors as a rejection", async () => {
  const real = await import('sigstore');
  const options = { tufCachePath: CACHE };
  const accept = await defaultCreateVerifier(options, { load: await fakeSigstore({}) });
  assert.equal(await accept({}), true);
  for (const error of [
    new real.VerificationError({ code: 'TLOG_INCLUSION_PROOF_ERROR', message: 'x' }),
    new real.PolicyError({ code: 'UNTRUSTED_SIGNER_ERROR', message: 'x' }),
    new real.ValidationError('bad bundle', ['mediaType']),
  ]) {
    const verify = await defaultCreateVerifier(options, { load: await fakeSigstore({ verifyError: error }) });
    assert.equal(await verify({}), false, error.name);
  }
  const broken = await defaultCreateVerifier(options, { load: await fakeSigstore({ verifyError: new TypeError('bug') }) });
  await assert.rejects(broken({}), TypeError);
});

test('the default verifier maps set-up failures: TUF to network, an unusable cache to preflight', async () => {
  const real = await import('sigstore');
  const options = { tufCachePath: CACHE };
  const tuf = new real.TUFError({ code: 'TUF_REFRESH_METADATA_ERROR', message: 'x', cause: Object.assign(new TypeError('fetch failed'), { cause: { code: 'ETIMEDOUT' } }) });
  await assert.rejects(defaultCreateVerifier(options, { load: await fakeSigstore({ createError: tuf }) }),
    (e) => e instanceof NetworkError && e.code === 'NETWORK' && /ETIMEDOUT/.test(e.message));
  const denied = Object.assign(new Error('EACCES: permission denied'), { code: 'EACCES', syscall: 'mkdir' });
  await assert.rejects(defaultCreateVerifier(options, { load: await fakeSigstore({ createError: denied }) }),
    (e) => e.code === 'PREFLIGHT' && e.message.includes(CACHE));
  await assert.rejects(defaultCreateVerifier(options, { load: await fakeSigstore({ createError: new TypeError('bug') }) }), TypeError);
  const missing = Object.assign(new Error("Cannot find package 'sigstore'"), { code: 'ERR_MODULE_NOT_FOUND' });
  await assert.rejects(defaultCreateVerifier(options, { load: async () => { throw missing; } }), (e) => e === missing);
});

test('a set-up SyntaxError is a corrupt cache file when one fails to parse, otherwise a bad mirror answer', async (t) => {
  const dir = await mkdtemp(join(tmpdir(), 'cb-tuf-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const repo = join(dir, 'tuf-repo-cdn.sigstore.dev');
  await mkdir(join(repo, 'targets'), { recursive: true });
  await writeFile(join(repo, 'root.json'), '{"signed": {}}');
  await writeFile(join(repo, 'targets', 'trusted_root.json'), '{}');
  const options = { tufCachePath: dir };
  const syntax = () => new SyntaxError('Unexpected end of JSON input');
  await assert.rejects(defaultCreateVerifier(options, { load: await fakeSigstore({ createError: syntax() }) }),
    (e) => e instanceof NetworkError && /not JSON/.test(e.message));
  await writeFile(join(repo, 'timestamp.json'), '{"signed": {"_ty');
  await assert.rejects(defaultCreateVerifier(options, { load: await fakeSigstore({ createError: syntax() }) }),
    (e) => e.code === 'PREFLIGHT' && e.message.includes(join(repo, 'timestamp.json')) && /remove it and retry/.test(e.message));
});

test('real sigstore: a truncated cached root.json is a preflight error naming the cache', async (t) => {
  const dir = await mkdtemp(join(tmpdir(), 'cb-tuf-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const repo = join(dir, 'sigstore', 'tuf-repo-cdn.sigstore.dev');
  await mkdir(join(repo, 'targets'), { recursive: true });
  await writeFile(join(repo, 'root.json'), '{"signed": {"_type": "ro');
  await assert.rejects(defaultCreateVerifier({ tufCachePath: join(dir, 'sigstore'), retry: { retries: 0 }, timeout: 2000 }),
    (e) => e.code === 'PREFLIGHT' && e.message.includes(join(dir, 'sigstore')) && e.message.includes('root.json'));
});

test('real sigstore: an unreachable TUF mirror is a network error', async (t) => {
  const seeds = require('@sigstore/tuf/seeds.json');
  const dir = await mkdtemp(join(tmpdir(), 'cb-tuf-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  await writeFile(join(dir, 'root.json'), Buffer.from(seeds['https://tuf-repo-cdn.sigstore.dev']['root.json'], 'base64'));
  const closed = net.createServer();
  await new Promise((r) => closed.listen(0, '127.0.0.1', r));
  const { port } = closed.address();
  await new Promise((r) => closed.close(r));
  await assert.rejects(defaultCreateVerifier({
    tufMirrorURL: `http://127.0.0.1:${port}`,
    tufRootPath: join(dir, 'root.json'),
    tufCachePath: join(dir, 'cache'),
    retry: { retries: 0 },
    timeout: 2000,
  }), (e) => e instanceof NetworkError && /ECONNREFUSED/.test(e.message));
});

test('real sigstore: a cache directory it cannot write is a preflight error', async (t) => {
  if (process.getuid?.() === 0) {
    t.skip('root ignores directory permissions');
    return;
  }
  const dir = await mkdtemp(join(tmpdir(), 'cb-tuf-'));
  t.after(async () => { await chmod(join(dir, 'locked'), 0o700); await rm(dir, { recursive: true, force: true }); });
  await mkdir(join(dir, 'locked'), { mode: 0o500 });
  await chmod(join(dir, 'locked'), 0o500);
  await assert.rejects(defaultCreateVerifier({ tufCachePath: join(dir, 'locked', 'sigstore') }),
    (e) => e.code === 'PREFLIGHT' && /EACCES/.test(e.message));
});

test('the default verifier loads sigstore lazily, and sigstore exposes what it needs', async () => {
  assert.equal(typeof defaultCreateVerifier, 'function');
  const mod = await import('sigstore');
  for (const name of ['createVerifier', 'TUFError', 'VerificationError', 'PolicyError', 'ValidationError']) {
    assert.equal(typeof mod[name], 'function', name);
  }
});
