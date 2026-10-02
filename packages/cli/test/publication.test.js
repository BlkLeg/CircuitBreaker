import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { publishExact, integrity } from '../../../scripts/ci/cli_publish.mjs';

async function fixture({ exists = false, mismatch = false, noProvenance = false, networkError = false, tampered = false } = {}) {
  const dir = await mkdtemp(join(tmpdir(), 'cb-publish-'));
  const bytes = Buffer.from('accepted candidate bytes');
  const tarball = join(dir, 'cli.tgz');
  await writeFile(tarball, bytes);
  const calls = [];
  const inspect = () => ({ name: '@blkleg/circuitbreaker', version: '0.4.7', private: false, repository: { url: 'git+https://github.com/BlkLeg/CircuitBreaker.git' } });
  let present = exists;
  const runNpm = async (args) => {
    calls.push(args);
    if (args[0] === 'view') {
      if (networkError) throw Error('network failure');
      if (!present) throw Object.assign(Error('absent'), { code: 'E404' });
      return JSON.stringify({ integrity: mismatch ? 'sha512-other' : integrity(bytes), attestations: noProvenance ? {} : { url: 'https://registry.npmjs.org/-/npm/v1/attestations/@blkleg%2fcircuitbreaker@0.4.7' } });
    }
    if (args[0] === 'publish') present = true;
    if (args[0] === 'pack') {
      const destination = args[args.indexOf('--pack-destination') + 1];
      await writeFile(join(destination, 'cli.tgz'), tampered ? Buffer.from('different') : bytes);
      return JSON.stringify([{ filename: 'cli.tgz' }]);
    }
    return '';
  };
  return { tarball, version: '0.4.7', inspect, runNpm, calls };
}

test('publish uses exact accepted tarball; tags only after round-trip and provenance checks', async () => {
  const f = await fixture();
  const evidence = await publishExact(f);
  const publish = f.calls.find((args) => args[0] === 'publish');
  assert.equal(publish[1], f.tarball);
  assert.ok(publish.includes('--provenance'));
  assert.ok(publish.includes('--tag=cb-verified'));
  assert.equal(evidence.registry_round_trip, 'verified');
  assert.deepEqual(f.calls.slice(-2).map((args) => args[0]), ['audit', 'dist-tag']);
});

test('matching existing version is verified without republishing', async () => {
  const f = await fixture({ exists: true });
  await publishExact(f);
  assert.ok(!f.calls.some((args) => args[0] === 'publish'));
});

test('mismatch, missing provenance, network fault and substituted registry bytes never promote a tag', async () => {
  for (const options of [{ exists: true, mismatch: true }, { noProvenance: true }, { networkError: true }, { tampered: true }]) {
    const f = await fixture(options);
    await assert.rejects(publishExact(f));
    assert.ok(!f.calls.some((args) => args[0] === 'dist-tag'));
  }
});
