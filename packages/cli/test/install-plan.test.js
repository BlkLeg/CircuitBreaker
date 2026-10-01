import { test } from 'node:test';
import assert from 'node:assert/strict';
import { generateKeyPairSync, sign, createHash } from 'node:crypto';
import { mkdtemp, mkdir, writeFile, readdir, readFile as fsReadFile, stat, realpath } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, relative } from 'node:path';
import { run } from '../src/main.js';
import { EXIT } from '../src/exit-codes.js';
import { parseTrustedKeys } from '../src/release-trust.js';
import { RELEASE_API } from '../src/release-resolve.js';
import { ATTESTATION_API } from '../src/attestation.js';
import { makeTarGz } from './helpers/tar.js';

const DL = 'https://github.com/BlkLeg/CircuitBreaker/releases/download';
const name = (version) => `circuit-breaker_${version}_linux_amd64.tar.gz`;

// One release's files: a tarball, its SHA256SUMS and (optionally) a signature by
// a throwaway key that the returned `keys` trust, or by another key they do not.
function release({ version = '0.4.7', signed = true, trusted = true } = {}) {
  const tarball = makeTarGz([{ name: 'bin/circuit-breaker', data: Buffer.from('#!/bin/sh\n') }]);
  const sha256 = createHash('sha256').update(tarball).digest('hex');
  const sums = Buffer.from(`${sha256}  ./${name(version)}\n`);
  const { publicKey, privateKey } = generateKeyPairSync('ed25519');
  const raw = publicKey.export({ format: 'der', type: 'spki' }).subarray(-32);
  const keyId = createHash('sha256').update(raw).digest('hex').slice(0, 16);
  const signer = trusted ? privateKey : generateKeyPairSync('ed25519').privateKey;
  const sig = signed ? Buffer.from(sign(null, sums, signer).toString('base64')) : null;
  return { version, tarball, sha256, sums, sig, keyId, keys: parseTrustedKeys(`${keyId} ${raw.toString('base64')} 0.4.7 test`) };
}

// GitHub as the CLI sees it: the release JSON by tag and by list, and each asset
// by its download URL. `overrides` maps a URL to a handler; every call is kept.
function github(rel, { prerelease = false, overrides = {} } = {}) {
  const files = [[name(rel.version), rel.tarball], ['SHA256SUMS', rel.sums]];
  if (rel.sig) files.push(['SHA256SUMS.sig', rel.sig]);
  const assets = files.map(([n, bytes], i) => ({ id: 100 + i, name: n, size: bytes.length, browser_download_url: `${DL}/v${rel.version}/${n}` }));
  const json = { tag_name: `v${rel.version}`, draft: false, prerelease, assets };
  const routes = {
    [`${RELEASE_API}/tags/v${rel.version}`]: () => Response.json(json),
    [`${RELEASE_API}?per_page=30`]: () => Response.json([json]),
    ...Object.fromEntries(files.map(([n, bytes]) => [`${DL}/v${rel.version}/${n}`, () => new Response(bytes)])),
    ...overrides,
  };
  const calls = [];
  const fetchImpl = async (url) => {
    calls.push(url);
    const route = routes[url];
    return route ? route() : new Response('not found', { status: 404 });
  };
  return { fetchImpl, calls, tarballUrl: `${DL}/v${rel.version}/${name(rel.version)}` };
}

async function host({ fetchImpl, keys, identity = null, env = {} } = {}) {
  const root = await mkdtemp(join(tmpdir(), 'cb-plan-'));
  const identityPath = join(root, 'install-identity.json');
  if (identity) {
    await writeFile(identityPath, JSON.stringify({ schema_version: 1, mode: 'native', installed_at: '2026-09-30T00:00:00Z', ...identity }));
  }
  const output = { out: '', err: '' };
  const attested = [];
  const deps = {
    env: { XDG_CACHE_HOME: join(root, 'cache'), CB_IDENTITY_PATH: identityPath, ...env },
    home: join(root, 'home'),
    euid: process.geteuid(),
    out: (t) => { output.out += t; },
    err: (t) => { output.err += t; },
    readFile: fsReadFile, stat, realpath,
    trustedUids: [process.getuid()],
    cliVersion: '0.4.7',
    fetchImpl: fetchImpl ?? (async (url) => { throw new Error(`unexpected fetch of ${url}`); }),
    statfs: async () => ({ bavail: 1e9, bsize: 4096 }),
    sleep: async () => {},
    attest: async (sha) => { attested.push(sha); return { ok: true }; },
    keys: keys ?? [],
    arch: 'amd64',
  };
  return { root, deps, output, attested, staging: (v) => join(root, 'cache', 'circuitbreaker', 'staging', `${v}-amd64`) };
}

async function filesUnder(dir) {
  const found = [];
  for (const entry of await readdir(dir, { withFileTypes: true, recursive: true })) {
    if (entry.isFile()) found.push(join(entry.parentPath ?? entry.path, entry.name));
  }
  return found;
}

// A bundle directory on disk, as an operator copies it for --local-bundle.
async function localBundle(rel, { withSig = true } = {}) {
  const dir = await mkdtemp(join(tmpdir(), 'cb-local-'));
  await writeFile(join(dir, name(rel.version)), rel.tarball);
  await writeFile(join(dir, 'SHA256SUMS'), rel.sums);
  if (withSig && rel.sig) await writeFile(join(dir, 'SHA256SUMS.sig'), rel.sig);
  return join(dir, name(rel.version));
}

function noNetwork() {
  const calls = [];
  return { calls, fetchImpl: async (url) => { calls.push(url); throw new Error(`air gap broken: ${url}`); } };
}

test('install without --plan is not in this build and names install --plan', async () => {
  const h = await host();
  assert.equal(await run(['install'], h.deps), EXIT.UNSUPPORTED);
  assert.match(h.output.err, /install --plan/);
  assert.equal(h.output.out, '');
});

test('--version with --channel, unknown options and malformed versions are usage errors before any fetch', async () => {
  for (const argv of [
    ['--plan', '--version', '0.4.7', '--channel', 'stable'],
    ['--plan', '--frobnicate'],
    ['--plan', 'extra'],
    ['--plan', '--version', '../../evil'],
    ['--plan', '--version', ''],
    ['--plan', '--local-bundle', '/tmp/x.tar.gz', '--version', '0.4.7'],
    ['--plan', '--channel', 'nightly'],
  ]) {
    const net = noNetwork();
    const h = await host({ fetchImpl: net.fetchImpl });
    assert.equal(await run(['install', ...argv], h.deps), EXIT.USAGE, argv.join(' '));
    assert.match(h.output.err, /^circuitbreaker install: /, argv.join(' '));
    assert.deepEqual(net.calls, [], argv.join(' '));
  }
});

test('an online plan resolves, stages and verifies, and writes only inside staging', async () => {
  const rel = release();
  const gh = github(rel);
  const h = await host({ fetchImpl: gh.fetchImpl, keys: rel.keys });
  assert.equal(await run(['install', '--plan', '--version', '0.4.7'], h.deps), EXIT.OK, h.output.err);
  const out = h.output.out;
  assert.match(out, /^Install plan \(no changes made\)\n/);
  assert.match(out, /\nTarget     v0\.4\.7 \(linux amd64\)\n/);
  assert.match(out, new RegExp(`\\nBundle     ${h.staging('0.4.7').replace(/[.*+?^${}()|[\]\\/]/g, '\\$&')}/${name('0.4.7').replace(/\./g, '\\.')}\\n`));
  assert.match(out, new RegExp(`\\nSHA256     ${rel.sha256}\\n`));
  assert.match(out, new RegExp(`\\nSignature  verified, key ${rel.keyId}\\n`));
  assert.match(out, /\nProvenance verified\n/);
  assert.match(out, /\nArchive    1 entry, 10 bytes unpacked; no unsafe paths or types\n/);
  assert.equal(h.output.err, '');
  assert.deepEqual(h.attested, [rel.sha256]);
  for (const file of await filesUnder(h.root)) {
    assert.ok(!relative(h.staging('0.4.7'), file).startsWith('..'), `${file} was written outside staging`);
  }
});

test('the default target is this CLI release, and a channel picks the newest eligible one', async () => {
  const rel = release();
  const gh = github(rel);
  const h = await host({ fetchImpl: gh.fetchImpl, keys: rel.keys });
  assert.equal(await run(['install', '--plan'], h.deps), EXIT.OK, h.output.err);
  assert.equal(gh.calls[0], `${RELEASE_API}/tags/v0.4.7`);
  assert.match(h.output.out, /Target     v0\.4\.7 \(linux amd64\)\n/);

  const candidate = github(rel, { prerelease: true });
  const c = await host({ fetchImpl: candidate.fetchImpl, keys: rel.keys });
  assert.equal(await run(['install', '--plan', '--channel', 'candidate'], c.deps), EXIT.OK, c.output.err);
  assert.equal(candidate.calls[0], `${RELEASE_API}?per_page=30`);
  assert.match(c.output.out, /Target     v0\.4\.7 \(linux amd64, candidate channel\)\n/);

  const stable = await host({ fetchImpl: github(rel, { prerelease: true }).fetchImpl, keys: rel.keys });
  assert.equal(await run(['install', '--plan', '--channel', 'stable'], stable.deps), EXIT.UNSUPPORTED);
  assert.match(stable.output.err, /no stable release is published/);
});

test('a signature by an untrusted key is refused with the keys tried', async () => {
  const rel = release({ trusted: false });
  const trustedOnly = release();
  const h = await host({ fetchImpl: github(rel).fetchImpl, keys: trustedOnly.keys });
  assert.equal(await run(['install', '--plan', '--version', '0.4.7'], h.deps), EXIT.TRUST);
  assert.match(h.output.err, new RegExp(`does not verify.*Keys tried: ${trustedOnly.keyId}`));
  assert.equal(h.output.out, '');
  assert.deepEqual(h.attested, []);
});

test('an unsigned newest release is refused', async () => {
  const rel = release({ signed: false });
  const h = await host({ fetchImpl: github(rel).fetchImpl, keys: rel.keys });
  assert.equal(await run(['install', '--plan'], h.deps), EXIT.TRUST);
  assert.match(h.output.err, /publishes no SHA256SUMS\.sig/);
});

test('missing provenance online is a trust refusal; provenance network and cache faults keep their own codes', async () => {
  const rel = release();
  const h = await host({ fetchImpl: github(rel).fetchImpl, keys: rel.keys });
  h.deps.attest = async () => ({ ok: false, reason: 'none' });
  assert.equal(await run(['install', '--plan'], h.deps), EXIT.TRUST);
  assert.match(h.output.err, /build provenance could not be verified \(none\)/);

  const n = await host({ fetchImpl: github(rel).fetchImpl, keys: rel.keys });
  n.deps.attest = async () => { throw Object.assign(new Error("could not load sigstore's trusted root"), { code: 'NETWORK' }); };
  assert.equal(await run(['install', '--plan'], n.deps), EXIT.NETWORK);
  assert.match(n.output.err, /trusted root/);

  const p = await host({ fetchImpl: github(rel).fetchImpl, keys: rel.keys });
  p.deps.attest = async () => { throw Object.assign(new Error('the sigstore cache is not usable (EACCES)'), { code: 'PREFLIGHT' }); };
  assert.equal(await run(['install', '--plan'], p.deps), EXIT.PREFLIGHT);
});

test('without an injected attest, provenance is looked up through the injected fetch', async () => {
  const rel = release();
  const gh = github(rel);
  const h = await host({ fetchImpl: gh.fetchImpl, keys: rel.keys });
  delete h.deps.attest;
  assert.equal(await run(['install', '--plan'], h.deps), EXIT.TRUST);
  assert.match(h.output.err, /build provenance could not be verified \(none\)/);
  assert.ok(gh.calls.includes(`${ATTESTATION_API}/sha256:${rel.sha256}`), gh.calls.join('\n'));
});

test('--airgap needs --local-bundle', async () => {
  for (const env of [{}, { CB_AIRGAP: 'TRUE' }]) {
    const net = noNetwork();
    const h = await host({ fetchImpl: net.fetchImpl, env });
    const argv = env.CB_AIRGAP ? ['install', '--plan'] : ['install', '--plan', '--airgap'];
    assert.equal(await run(argv, h.deps), EXIT.USAGE);
    assert.match(h.output.err, /air-gap installs need --local-bundle/);
    assert.deepEqual(net.calls, []);
  }
});

test('an air-gapped local bundle verifies with zero network requests', async () => {
  const rel = release();
  for (const [argv, env] of [[['--airgap'], {}], [[], { CB_AIRGAP: 'true' }], [[], { CB_AIRGAP: 'On' }]]) {
    const net = noNetwork();
    const h = await host({ fetchImpl: net.fetchImpl, keys: rel.keys, env });
    const bundle = await localBundle(rel);
    assert.equal(await run(['install', '--plan', ...argv, '--local-bundle', bundle], h.deps), EXIT.OK, h.output.err);
    assert.match(h.output.out, /\nTarget     v0\.4\.7 \(linux amd64, local bundle\)\n/);
    assert.match(h.output.out, new RegExp(`\\nBundle     ${bundle.replace(/[.*+?^${}()|[\]\\/]/g, '\\$&')}\\n`));
    assert.match(h.output.out, /\nProvenance skipped \(air-gapped\)\n/);
    assert.deepEqual(net.calls, []);
    assert.deepEqual(h.attested, []);
    await assert.rejects(stat(join(h.root, 'cache')), { code: 'ENOENT' }, 'a local bundle is verified in place, never staged');
  }
});

test('a local bundle online still has its provenance checked', async () => {
  const rel = release();
  const net = noNetwork();
  const h = await host({ fetchImpl: net.fetchImpl, keys: rel.keys });
  assert.equal(await run(['install', '--plan', '--local-bundle', await localBundle(rel)], h.deps), EXIT.OK, h.output.err);
  assert.deepEqual(h.attested, [rel.sha256]);
  assert.match(h.output.out, /\nProvenance verified\n/);
  assert.deepEqual(net.calls, [], 'only provenance may go online, and attest is injected here');
});

test('a local bundle with SHA256SUMS but no signature is refused', async () => {
  const rel = release();
  const h = await host({ keys: rel.keys, env: { CB_AIRGAP: 'yes' } });
  assert.equal(await run(['install', '--plan', '--local-bundle', await localBundle(rel, { withSig: false })], h.deps), EXIT.TRUST);
  assert.match(h.output.err, /no SHA256SUMS\.sig next to/);
});

test('a missing local bundle is a usage error', async () => {
  const h = await host({ env: { CB_AIRGAP: '1' } });
  const dir = await mkdtemp(join(tmpdir(), 'cb-local-'));
  assert.equal(await run(['install', '--plan', '--local-bundle', join(dir, name('0.4.7'))], h.deps), EXIT.USAGE);
  assert.match(h.output.err, /no bundle at /);
  await mkdir(join(dir, 'adir'));
  assert.equal(await run(['install', '--plan', '--local-bundle', join(dir, 'adir')], h.deps), EXIT.USAGE);
});

test('a tarball that answers 503 every time is a network failure after 4 attempts', async () => {
  const rel = release();
  const calls = { n: 0 };
  const gh = github(rel, { overrides: { [`${DL}/v0.4.7/${name('0.4.7')}`]: () => { calls.n += 1; return new Response('busy', { status: 503 }); } } });
  const h = await host({ fetchImpl: gh.fetchImpl, keys: rel.keys });
  assert.equal(await run(['install', '--plan'], h.deps), EXIT.NETWORK);
  assert.equal(calls.n, 4);
  assert.match(h.output.err, /HTTP 503/);
});

test('too little disk space for the bundle is a preflight failure', async () => {
  const rel = release();
  const h = await host({ fetchImpl: github(rel).fetchImpl, keys: rel.keys });
  h.deps.statfs = async () => ({ bavail: 1, bsize: 4096 });
  assert.equal(await run(['install', '--plan'], h.deps), EXIT.PREFLIGHT);
  assert.match(h.output.err, /not enough free space/);
});

test('a release that is not published is unsupported', async () => {
  const h = await host({ fetchImpl: github(release()).fetchImpl });
  assert.equal(await run(['install', '--plan', '--version', '9.9.9'], h.deps), EXIT.UNSUPPORTED);
  assert.match(h.output.err, /release v9\.9\.9 not found/);
});

test('--json prints exactly one result object, verified or refused', async () => {
  const rel = release();
  const h = await host({ fetchImpl: github(rel).fetchImpl, keys: rel.keys });
  assert.equal(await run(['install', '--plan', '--json', '--version', 'v0.4.7'], h.deps), EXIT.OK, h.output.err);
  assert.deepEqual(JSON.parse(h.output.out), {
    schema_version: 1, action: 'install', plan: true, outcome: 'verified',
    target: { version: '0.4.7', channel: null, arch: 'amd64', explicit_version: true },
    bundle: { name: name('0.4.7'), sha256: rel.sha256, path: join(h.staging('0.4.7'), name('0.4.7')) },
    trust: { signature: { key_id: rel.keyId }, provenance: 'verified' },
    archive: { entries: 1, total_bytes: 10 },
    server: null,
  });
  assert.equal(h.output.out.trim().split('\n').length, 1);

  const bad = release({ trusted: false });
  const r = await host({ fetchImpl: github(bad).fetchImpl, keys: rel.keys });
  assert.equal(await run(['install', '--plan', '--json'], r.deps), EXIT.TRUST);
  const refused = JSON.parse(r.output.out);
  assert.deepEqual(Object.keys(refused), ['schema_version', 'action', 'plan', 'outcome', 'error']);
  assert.equal(refused.outcome, 'refused');
  assert.equal(refused.error.code, 'TRUST');
  assert.match(refused.error.reason, new RegExp(`Keys tried: ${rel.keyId}`));
  assert.equal(r.output.out.trim().split('\n').length, 1);

  const u = await host({ env: { CB_AIRGAP: 'true' } });
  assert.equal(await run(['install', '--plan', '--json'], u.deps), EXIT.USAGE);
  assert.deepEqual(JSON.parse(u.output.out).error, { code: 'USAGE', reason: 'air-gap installs need --local-bundle PATH' });
});

test('--json reports an accepted unsigned older release as such', async () => {
  const rel = release({ version: '0.4.3', signed: false });
  const h = await host({ fetchImpl: github(rel).fetchImpl, keys: rel.keys });
  assert.equal(await run(['install', '--plan', '--json', '--version', '0.4.3'], h.deps), EXIT.OK, h.output.err);
  const result = JSON.parse(h.output.out);
  assert.deepEqual(result.trust, { signature: { unsigned: 'explicit-older' }, provenance: 'not-applicable' });
  assert.deepEqual(h.attested, []);
});

test('an existing install is reported, and the plan says an install would be an update', async () => {
  const rel = release();
  const h = await host({ fetchImpl: github(rel).fetchImpl, keys: rel.keys, identity: { version: '0.4.6' } });
  assert.equal(await run(['install', '--plan'], h.deps), EXIT.OK, h.output.err);
  assert.match(h.output.out, /This host already runs Circuit Breaker 0\.4\.6; an install would be an update \(sub-plan 05\)\.\n$/);

  const j = await host({ fetchImpl: github(rel).fetchImpl, keys: rel.keys, identity: { version: '0.4.6' } });
  assert.equal(await run(['install', '--plan', '--json'], j.deps), EXIT.OK, j.output.err);
  assert.deepEqual(JSON.parse(j.output.out).server, { version: '0.4.6', mode: 'native' });
});

test('help lists install --plan under this CLI and says host-changing installs come later', async () => {
  const h = await host();
  assert.equal(await run(['help'], h.deps), EXIT.OK);
  assert.match(h.output.out, /This CLI:\n {2}install --plan +Resolve, download and verify a release; changes nothing \[--json\]\n/);
  assert.match(h.output.out, /\nInstall, update and uninstall that change the host arrive in later builds; `install --plan` shows what an install would do\.\n/);
});
