import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, stat, realpath, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { generateKeyPairSync, createHash, sign } from 'node:crypto';
import { makeTarGz } from './helpers/tar.js';
import { parseTrustedKeys } from '../src/release-trust.js';
import { run } from '../src/main.js';
import { compareVersions } from '../src/lifecycle.js';

async function fixture({ installed = null, version = '0.4.8', mismatched = false, mode = 'native' } = {}) {
  const dir = await mkdtemp(join(tmpdir(), 'cb-lifecycle-'));
  const identity = join(dir, 'identity.json');
  if (installed) await writeFile(identity, JSON.stringify({ schema_version: 1, mode, version: installed, installed_at: '2026-10-02', cli_path: '/usr/bin/echo' }));
  const name = `circuit-breaker_${version}_linux_amd64.tar.gz`;
  const bundle = join(dir, name);
  const bytes = makeTarGz([{ name: 'install.sh', data: Buffer.from('#!/bin/bash\nexit 0\n') }, { name: 'share/VERSION', data: Buffer.from(mismatched ? '0.4.6' : version) }]);
  const hash = createHash('sha256').update(bytes).digest('hex');
  const sums = Buffer.from(`${hash}  ${name}\n`);
  const { publicKey, privateKey } = generateKeyPairSync('ed25519');
  const raw = publicKey.export({ format: 'der', type: 'spki' }).subarray(-32);
  const key = createHash('sha256').update(raw).digest('hex').slice(0, 16);
  await writeFile(bundle, bytes);
  await writeFile(join(dir, 'SHA256SUMS'), sums);
  await writeFile(join(dir, 'SHA256SUMS.sig'), sign(null, sums, privateKey).toString('base64'));
  const io = { out: '', err: '', steps: [] };
  const deps = { env: { CB_IDENTITY_PATH: identity }, home: dir, euid: process.geteuid(), trustedUids: [process.getuid()], readFile, stat, realpath, cliVersion: '0.4.7', arch: 'amd64', keys: parseTrustedKeys(`${key} ${raw.toString('base64')}`), out: (s) => { io.out += s; }, err: (s) => { io.err += s; }, fetchImpl: async () => { throw Error('unexpected network request'); }, nativeStep: async (step) => { io.steps.push(step); return { code: 0, result: { schema_version: 1, action: installed ? 'update' : 'install', operation_id: 'op-20261002-001', outcome: 'committed', current_version: version, target_version: version, recovery_available: Boolean(installed) } }; } };
  return { dir, bundle, deps, io };
}

test('fresh install verifies offline and invokes only native bash with literal options', async () => {
  const f = await fixture();
  assert.equal(await run(['install', '--yes', '--json', '--airgap', '--local-bundle', f.bundle, '--fqdn', '$(touch pwned)'], f.deps), 0, f.io.err);
  assert.equal(f.io.steps.length, 1);
  assert.equal(f.io.steps[0].cliPath, process.geteuid() === 0 ? '/bin/bash' : '/usr/bin/sudo');
  assert.ok(f.io.steps[0].args.includes('$(touch pwned)'));
  assert.equal(JSON.parse(f.io.out).outcome, 'committed');
});

test('same-version verified update is a no-op; older target refuses before native apply', async () => {
  for (const [installed, code] of [['0.4.8', 0], ['0.4.9', 3]]) {
    const f = await fixture({ installed });
    assert.equal(await run(['update', '--yes', '--json', '--airgap', '--local-bundle', f.bundle], f.deps), code, f.io.err);
    assert.equal(f.io.steps.length, 0);
  }
});

test('corrupt bundle and mismatched embedded version never start privileged work', async () => {
  for (const mismatched of [false, true]) {
    const f = await fixture({ mismatched });
    if (!mismatched) await writeFile(f.bundle, 'corrupt');
    assert.equal(await run(['install', '--yes', '--json', '--airgap', '--local-bundle', f.bundle], f.deps), 5, f.io.err);
    assert.equal(f.io.steps.length, 0);
  }
});

test('package and mono lifecycle apply refuse without invoking sudo', async () => {
  for (const mode of ['package', 'mono']) {
    const f = await fixture({ installed: '0.4.7', mode });
    assert.equal(await run(['update', '--yes'], f.deps), 3);
    assert.equal(f.io.steps.length, 0);
  }
});

test('native recovery result is preserved and absence of a result requires inspection', async () => {
  for (const missing of [false, true]) {
    const f = await fixture({ installed: '0.4.7' });
    f.deps.nativeStep = async () => ({ code: 8, result: missing ? null : { schema_version: 1, action: 'update', operation_id: 'op-20261002-001', outcome: 'recovered', current_version: '0.4.7', target_version: '0.4.8', recovery_available: true, error: { code: 'RECOVERED', reason: 'previous release restored' } } });
    assert.equal(await run(['update', '--yes', '--json', '--airgap', '--local-bundle', f.bundle], f.deps), missing ? 9 : 8, f.io.err);
  }
});

test('semantic ordering handles numeric versions and prereleases', () => {
  assert.equal(compareVersions('0.4.10', '0.4.9'), 1);
  assert.equal(compareVersions('1.0.0-rc.10', '1.0.0-rc.2'), 1);
  assert.equal(compareVersions('1.0.0-rc.2', '1.0.0'), -1);
  assert.equal(compareVersions('1.0.0', '1.0.0'), 0);
});

test('rollback cancellation never invokes the native adapter; explicit data consent is forwarded', async () => {
  const f = await fixture({ installed: '0.4.8' });
  f.deps.confirm = async () => false;
  assert.equal(await run(['rollback', '--restore-data'], f.deps), 2);
  assert.equal(f.io.steps.length, 0);
  const script = join(f.dir, 'rollback.sh');
  await writeFile(script, '#!/bin/bash\n');
  f.deps.realpath = async (path) => path.endsWith('rollback-release.sh') ? script : realpath(path);
  f.deps.nativeStep = async (step) => { f.io.steps.push(step); return { code: 0, result: { schema_version: 1, action: 'rollback', operation_id: 'op-20261002-001', outcome: 'committed', current_version: '0.4.7', target_version: '0.4.7', recovery_available: true } }; };
  assert.equal(await run(['rollback', '--yes', '--restore-data', '--json'], f.deps), 0, f.io.err);
  assert.ok(f.io.steps[0].args.includes('--restore-data'));
});

test('every option forwarded to the native installer is one install.sh accepts', async () => {
  const installer = await readFile(new URL('../../../install.sh', import.meta.url), 'utf8');
  const accepted = new Set([...installer.matchAll(/^\s*(--[a-z-]+)\)/gm)].map((m) => m[1]));
  const f = await fixture();
  const argv = ['install', '--yes', '--json', '--airgap', '--local-bundle', f.bundle, '--port', '8443', '--fqdn', 'cb.lan', '--email', 'a@b.c', '--cert-type', 'self-signed', '--data-dir', '/srv/cb', '--no-tls', '--force-deps'];
  assert.equal(await run(argv, f.deps), 0, f.io.err);
  const forwarded = f.io.steps[0].args.filter((arg) => arg.startsWith('--') && arg !== '--');
  assert.ok(forwarded.length > 8);
  for (const flag of forwarded) assert.ok(accepted.has(flag), `install.sh does not accept ${flag}`);
});

test('an option install.sh rejects is refused before any native work', async () => {
  const f = await fixture();
  assert.notEqual(await run(['install', '--yes', '--airgap', '--local-bundle', f.bundle, '--no-docker'], f.deps), 0);
  assert.equal(f.io.steps.length, 0);
});

test('an installer that stops before any operation is a refusal with its own reason and code', async () => {
  const f = await fixture();
  f.deps.nativeStep = async () => ({ code: 1, result: { schema_version: 1, action: 'install', operation_id: null, outcome: 'refused', current_version: null, target_version: null, recovery_available: false, error: { code: 'PREFLIGHT', reason: 'The installer stopped at a check before changing anything; its output above says why.' } } });
  assert.equal(await run(['install', '--yes', '--airgap', '--local-bundle', f.bundle], f.deps), 7);
  assert.match(f.io.err, /stopped at a check before changing anything/);
  assert.doesNotMatch(f.io.err, /no final result|did not match/);
});

test('with no native result, a lifecycle exit code is kept and anything else asks for inspection', async () => {
  for (const [native, expected, text] of [[10, 10, /before changing anything \(exit 10\)/], [7, 7, /before changing anything \(exit 7\)/], [1, 9, /without a final result \(exit 1\)/]]) {
    const f = await fixture();
    f.deps.nativeStep = async () => ({ code: native, result: null });
    assert.equal(await run(['install', '--yes', '--airgap', '--local-bundle', f.bundle], f.deps), expected);
    assert.match(f.io.err, text);
  }
});
