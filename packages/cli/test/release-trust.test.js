import { test } from 'node:test';
import assert from 'node:assert/strict';
import { generateKeyPairSync, sign, createHash } from 'node:crypto';
import {
  parseTrustedKeys, verifySumsSignature, findSumsEntry, isCanonicalVersion,
  releaseRequiresSignature, matchesUnsignedPin, TRUSTED_KEYS, UNSIGNED_PINS, FIRST_SIGNED_RELEASE,
} from '../src/release-trust.js';

function throwawayKey(first = '0.4.7') {
  const { publicKey, privateKey } = generateKeyPairSync('ed25519');
  const raw = publicKey.export({ format: 'der', type: 'spki' }).subarray(-32);
  const id = createHash('sha256').update(raw).digest('hex').slice(0, 16);
  return { privateKey, line: `${id} ${raw.toString('base64')} ${first} throwaway`, id };
}
const SUMS = Buffer.from(`${'ab'.repeat(32)}  ./circuit-breaker_0.4.7_linux_amd64.tar.gz\n`);
const sigOf = (key, data = SUMS) => sign(null, data, key.privateKey).toString('base64');

test('a good signature verifies and names its key', () => {
  const k = throwawayKey();
  assert.deepEqual(verifySumsSignature(SUMS, `${sigOf(k)}\n`, parseTrustedKeys(k.line)), { ok: true, keyId: k.id });
});

test('whitespace and CRLF around the signature are tolerated', () => {
  const k = throwawayKey();
  assert.equal(verifySumsSignature(SUMS, `  ${sigOf(k)}\r\n\r\n`, parseTrustedKeys(k.line)).ok, true);
});

test('tampered sums, untrusted key, no keys and unreadable signatures each fail distinctly', () => {
  const k = throwawayKey();
  const other = throwawayKey();
  const keys = parseTrustedKeys(k.line);
  assert.deepEqual(verifySumsSignature(Buffer.concat([SUMS, Buffer.from('x')]), sigOf(k), keys),
    { ok: false, reason: 'mismatch', tried: [k.id] });
  assert.equal(verifySumsSignature(SUMS, sigOf(other), keys).reason, 'mismatch');
  assert.equal(verifySumsSignature(SUMS, sigOf(k), []).reason, 'no-keys');
  for (const bad of ['', 'not base64 !!', Buffer.alloc(10).toString('base64')]) {
    assert.equal(verifySumsSignature(SUMS, bad, keys).reason, 'unreadable', JSON.stringify(bad));
  }
});

test('the second of two trusted keys is found; comments, blanks and forged ids are ignored', () => {
  const a = throwawayKey();
  const b = throwawayKey();
  const forged = `${'0'.repeat(16)} ${b.line.split(' ')[1]} 0.4.7 forged`;
  const keys = parseTrustedKeys(`# c\n\n${forged}\n${a.line}\r\n${b.line}\n`);
  assert.deepEqual(keys.map((key) => key.id), [a.id, b.id]);
  assert.deepEqual(verifySumsSignature(SUMS, sigOf(b), keys), { ok: true, keyId: b.id });
});

test('the hash entry is chosen by exact name, ./ or bare', () => {
  const name = 'circuit-breaker_0.4.7_linux_amd64.tar.gz';
  const text = `${'1'.repeat(64)}  ./${name}.asc\n${'2'.repeat(64)}  ${name}\n`;
  assert.equal(findSumsEntry(text, name), '2'.repeat(64));
  assert.equal(findSumsEntry(`${'3'.repeat(64)}  ./${name}\n`, name), '3'.repeat(64));
  assert.equal(findSumsEntry(`${'1'.repeat(64)}  ./${name}.asc\n`, name), null);
  assert.equal(findSumsEntry(text, `${name}(1)`), null);
});

test('version rules match the shell library', () => {
  assert.equal(FIRST_SIGNED_RELEASE, '0.4.7');
  for (const [v, required] of [['0.4.6', false], ['0.4.6-rc.1', false], ['0.3.9', false], ['0.4.7', true],
    ['0.4.7-rc.1', true], ['0.4.10', true], ['0.5.0', true], ['1.0.0-rc.4', true]]) {
    assert.equal(releaseRequiresSignature(v), required, v);
  }
  for (const [v, ok] of [['0.4.6', true], ['10.0.1', true], ['v0.4.6', false], ['00.4.7', false], ['0.4.6.1', false], ['0.4.7-rc.1', false]]) {
    assert.equal(isCanonicalVersion(v), ok, v);
  }
});

test('unsigned pins are the genuine v0.4.6 bundles only', () => {
  assert.equal(UNSIGNED_PINS.length, 2);
  const [pin] = UNSIGNED_PINS;
  assert.equal(matchesUnsignedPin(pin.sha256, pin.name), true);
  assert.equal(matchesUnsignedPin(pin.sha256, 'renamed.tar.gz'), false);
  assert.equal(matchesUnsignedPin('0'.repeat(64), pin.name), false);
});

test('the packaged key list parses to the real trusted key', () => {
  assert.ok(TRUSTED_KEYS.length >= 1);
  for (const key of TRUSTED_KEYS) assert.match(key.id, /^[0-9a-f]{16}$/);
});
