import { test } from 'node:test';
import assert from 'node:assert/strict';
import { verifyAttestation, ATTESTATION_API, ATTESTATION_IDENTITY, ATTESTATION_ISSUER } from '../src/attestation.js';

const DIGEST = 'a'.repeat(64);
const bundleFor = (digest) => ({
  dsseEnvelope: { payload: Buffer.from(JSON.stringify({ subject: [{ name: 'x', digest: { sha256: digest } }] })).toString('base64') },
});
const api = (bundles) => async (url) => {
  assert.equal(url, `${ATTESTATION_API}/sha256:${DIGEST}`);
  return { attestations: bundles.map((bundle) => ({ bundle })) };
};

test('passes the pinned issuer and workflow identity to sigstore and checks the subject digest', async () => {
  let options;
  const sigstoreVerify = async (bundle, opts) => { options = opts; };
  assert.deepEqual(await verifyAttestation({ sha256: DIGEST, fetchJson: api([bundleFor(DIGEST)]), sigstoreVerify }), { ok: true });
  assert.deepEqual(options, { certificateIssuer: ATTESTATION_ISSUER, certificateIdentityURI: ATTESTATION_IDENTITY });
  assert.equal(ATTESTATION_IDENTITY, 'https://github.com/BlkLeg/CircuitBreaker/.github/workflows/release.yml@refs/heads/main');
  assert.equal(ATTESTATION_ISSUER, 'https://token.actions.githubusercontent.com');
});

test('a bundle sigstore rejects, or one attesting another digest, does not count', async () => {
  const reject = async () => { throw new Error('bad'); };
  assert.deepEqual(await verifyAttestation({ sha256: DIGEST, fetchJson: api([bundleFor(DIGEST)]), sigstoreVerify: reject }), { ok: false, reason: 'unverified' });
  const accept = async () => {};
  assert.deepEqual(await verifyAttestation({ sha256: DIGEST, fetchJson: api([bundleFor('b'.repeat(64))]), sigstoreVerify: accept }), { ok: false, reason: 'unverified' });
});

test('one verified bundle for the digest is enough among rejected ones', async () => {
  const good = bundleFor(DIGEST);
  const sigstoreVerify = async (bundle) => { if (bundle !== good) throw new Error('bad'); };
  const bundles = [bundleFor(DIGEST), { dsseEnvelope: { payload: 'not json' } }, good];
  assert.deepEqual(await verifyAttestation({ sha256: DIGEST, fetchJson: api(bundles), sigstoreVerify }), { ok: true });
});

test('a verified bundle whose payload is not a statement does not count', async () => {
  const garbled = { dsseEnvelope: { payload: Buffer.from('not json').toString('base64') } };
  assert.deepEqual(await verifyAttestation({ sha256: DIGEST, fetchJson: api([garbled]), sigstoreVerify: async () => {} }), { ok: false, reason: 'unverified' });
});

test('no attestation at all is its own result', async () => {
  assert.deepEqual(await verifyAttestation({ sha256: DIGEST, fetchJson: api([]), sigstoreVerify: async () => {} }), { ok: false, reason: 'none' });
  const notFound = async () => { const e = new Error('404'); e.code = 'HTTP_STATUS'; e.status = 404; throw e; };
  assert.deepEqual(await verifyAttestation({ sha256: DIGEST, fetchJson: notFound, sigstoreVerify: async () => {} }), { ok: false, reason: 'none' });
});

test('any other fetch failure propagates to the caller', async () => {
  const unavailable = async () => { const e = new Error('503'); e.code = 'HTTP_STATUS'; e.status = 503; throw e; };
  await assert.rejects(verifyAttestation({ sha256: DIGEST, fetchJson: unavailable, sigstoreVerify: async () => {} }), /503/);
});

test('the default verifier loads sigstore lazily', async () => {
  const { defaultSigstoreVerify } = await import('../src/attestation.js');
  assert.equal(typeof defaultSigstoreVerify, 'function');
  const mod = await import('sigstore');
  assert.equal(typeof mod.verify, 'function');
});
