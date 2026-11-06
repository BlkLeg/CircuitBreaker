import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { snappyDecode, SnappyError } from '../src/snappy.js';

const bytes = (...parts) => Buffer.concat(parts.map((p) => (typeof p === 'string' ? Buffer.from(p) : Buffer.from(p))));
const rejectsAs = (input, pattern, options) => assert.throws(() => snappyDecode(input, options), (e) => e instanceof SnappyError && pattern.test(e.message));

test('decodes a short literal', () => {
  // length 5, then a literal tag for 5 bytes ((5-1) << 2).
  assert.equal(snappyDecode(bytes([5, 4 << 2], 'hello')).toString(), 'hello');
});

test('decodes a long literal whose length follows the tag', () => {
  const text = 'x'.repeat(300);
  // 300 = 0xac 0x02 as a varint; tag 61 << 2 carries a 2-byte length-1 (299 = 0x012b).
  assert.equal(snappyDecode(bytes([0xac, 0x02, 61 << 2, 0x2b, 0x01], text)).toString(), text);
});

test('decodes all three copy forms, overlapping ones included', () => {
  // "ab", then copy-1 of 4 at offset 2 ("abab"), copy-2 of 3 at offset 6 ("aba"), copy-4 of 2 at offset 1 ("aa").
  const input = bytes(
    [11],
    [1 << 2], 'ab',
    [0b01 | ((4 - 4) << 2) | (0 << 5), 2],
    [0b10 | ((3 - 1) << 2), 6, 0],
    [0b11 | ((2 - 1) << 2), 1, 0, 0, 0],
  );
  assert.equal(snappyDecode(input).toString(), 'ababababaaa');
});

test('an empty input of declared length 0 is empty', () => {
  assert.equal(snappyDecode(bytes([0])).length, 0);
});

test('corrupt input is a SnappyError, never a partial result', () => {
  rejectsAs(bytes([]), /length/);
  rejectsAs(bytes([0x80, 0x80, 0x80, 0x80, 0x80, 0x01]), /length/);
  rejectsAs(bytes([5, 4 << 2], 'hel'), /literal/);
  rejectsAs(bytes([5, 60 << 2]), /literal/);
  rejectsAs(bytes([4, 0b01]), /copy/);
  rejectsAs(bytes([6, 1 << 2], 'ab', [0b01, 0]), /offset/);
  rejectsAs(bytes([6, 1 << 2], 'ab', [0b01, 3]), /offset/);
  rejectsAs(bytes([3, 4 << 2], 'hello'), /declared/);
  rejectsAs(bytes([2, 1 << 2], 'ab', [0b01, 2]), /declared/);
  rejectsAs(bytes([9, 1 << 2], 'ab'), /declared/);
});

test('a declared length above the cap is refused before anything is allocated', () => {
  rejectsAs(bytes([0xff, 0xff, 0xff, 0xff, 0x0f]), /cap/, { maxLength: 1024 });
  rejectsAs(bytes([5, 4 << 2], 'hello'), /cap/, { maxLength: 4 });
});

test('decodes a real GitHub attestation blob into its sigstore bundle', async () => {
  // Fetched from the bundle_url of cli/cli's SLSA build provenance for gh_2.102.0_linux_amd64.tar.gz.
  const blob = await readFile(new URL('./fixtures/gh-slsa-provenance.snappy', import.meta.url));
  const bundle = JSON.parse(snappyDecode(blob).toString('utf8'));
  assert.match(bundle.mediaType, /^application\/vnd\.dev\.sigstore\.bundle/);
  const statement = JSON.parse(Buffer.from(bundle.dsseEnvelope.payload, 'base64').toString('utf8'));
  assert.equal(statement.predicateType, 'https://slsa.dev/provenance/v1');
  assert.ok(statement.subject.some((s) => s.digest?.sha256 === 'bb766f710eef8ede859c18578c72c327597cd4c8a85b06001b1f3843c6019386'));
});
