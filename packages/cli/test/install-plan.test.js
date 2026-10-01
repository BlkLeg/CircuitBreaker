import { test } from 'node:test';
import assert from 'node:assert/strict';
import { generateKeyPairSync, sign, createHash } from 'node:crypto';
import { existsSync } from 'node:fs';
import { mkdtemp, mkdir, writeFile, readdir, readFile as fsReadFile, stat, realpath, symlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, relative } from 'node:path';
import { run } from '../src/main.js';
import { EXIT } from '../src/exit-codes.js';
import { parseTrustedKeys } from '../src/release-trust.js';
import { RELEASE_API } from '../src/release-resolve.js';
import { ATTESTATION_API } from '../src/attestation.js';
import { makeTarGz } from './helpers/tar.js';
import { parseDocument } from '../src/lifecycle-contract.js';

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
  assert.deepEqual(await readdir(h.staging('0.4.7')), [], 'nothing is written before the space check');
});

test('a full disk while staging is a preflight failure with one JSON result, not a network retry', async (t) => {
  if (!existsSync('/dev/full')) {
    t.skip('needs /dev/full, which answers every write with ENOSPC (Linux)');
    return;
  }
  const rel = release();
  const tarballUrl = `${DL}/v0.4.7/${name('0.4.7')}`;
  const served = { n: 0 };
  const h = await host({ fetchImpl: github(rel, { overrides: { [tarballUrl]: () => { served.n += 1; return new Response(rel.tarball); } } }).fetchImpl, keys: rel.keys });
  // A .part whose writes land on /dev/full, as a full disk answers them.
  const dir = h.staging('0.4.7');
  await mkdir(dir, { recursive: true, mode: 0o700 });
  await writeFile(join(dir, `${name('0.4.7')}.asset.json`), JSON.stringify({ id: 100, size: rel.tarball.length, url: tarballUrl }));
  await symlink('/dev/full', join(dir, `${name('0.4.7')}.part`));
  assert.equal(await run(['install', '--plan', '--json'], h.deps), EXIT.PREFLIGHT);
  const refused = JSON.parse(h.output.out);
  assert.equal(refused.error.code, 'PREFLIGHT');
  assert.match(refused.error.reason, /no space left/);
  assert.equal(served.n, 1);
});

test('out-of-space and quota errors from any step are preflight failures', async () => {
  const rel = release();
  for (const code of ['ENOSPC', 'EDQUOT']) {
    const h = await host({ fetchImpl: github(rel).fetchImpl, keys: rel.keys });
    h.deps.attest = async () => { throw Object.assign(new Error(`${code}: no space left on device, write`), { code }); };
    assert.equal(await run(['install', '--plan', '--json'], h.deps), EXIT.PREFLIGHT, code);
    assert.equal(JSON.parse(h.output.out).error.code, 'PREFLIGHT', code);
  }
});

test('a staged file that fails verification is discarded, so the next run downloads it afresh', async () => {
  const rel = release();
  const gh = github(rel);
  const h = await host({ fetchImpl: gh.fetchImpl, keys: rel.keys });
  assert.equal(await run(['install', '--plan'], h.deps), EXIT.OK, h.output.err);
  const staged = join(h.staging('0.4.7'), name('0.4.7'));
  const bytes = await fsReadFile(staged);
  bytes[bytes.length - 1] ^= 1;
  await writeFile(staged, bytes);
  h.output.err = '';
  assert.equal(await run(['install', '--plan'], h.deps), EXIT.TRUST);
  assert.match(h.output.err, /SHA256 mismatch/);
  assert.match(h.output.err, /discarded/);
  assert.deepEqual(await readdir(h.staging('0.4.7')), []);
  const fetched = () => gh.calls.filter((url) => url === gh.tarballUrl).length;
  const before = fetched();
  h.output.err = '';
  assert.equal(await run(['install', '--plan'], h.deps), EXIT.OK, h.output.err);
  assert.equal(fetched(), before + 1);
});

test('a download refused once is fetched again on the next run, never reused from staging', async () => {
  const rel = release();
  for (const file of [name('0.4.7'), 'SHA256SUMS', 'SHA256SUMS.sig']) {
    const good = { [name('0.4.7')]: rel.tarball, SHA256SUMS: rel.sums, 'SHA256SUMS.sig': rel.sig }[file];
    const bad = Buffer.from(good);
    bad[0] ^= 1;
    const served = { n: 0 };
    const url = `${DL}/v0.4.7/${file}`;
    const h = await host({ fetchImpl: github(rel, { overrides: { [url]: () => new Response(served.n++ === 0 ? bad : good) } }).fetchImpl, keys: rel.keys });
    assert.equal(await run(['install', '--plan', '--json'], h.deps), EXIT.TRUST, file);
    assert.equal(JSON.parse(h.output.out).error.code, 'TRUST', file);
    h.output.out = '';
    assert.equal(await run(['install', '--plan', '--json'], h.deps), EXIT.OK, `${file}: ${h.output.err}`);
    assert.equal(served.n, 2, file);
  }
});

test('a GitHub answer that is not JSON is a network failure, from the release or the attestation API', async () => {
  const rel = release();
  const html = () => new Response('<html>rate limited</html>');
  const r = await host({ fetchImpl: github(rel, { overrides: { [`${RELEASE_API}/tags/v0.4.7`]: html } }).fetchImpl, keys: rel.keys });
  assert.equal(await run(['install', '--plan', '--json'], r.deps), EXIT.NETWORK);
  assert.equal(JSON.parse(r.output.out).error.code, 'NETWORK');
  assert.match(r.output.err, /api\.github\.com answered with something that is not JSON/);

  const a = await host({ fetchImpl: github(rel, { overrides: { [`${ATTESTATION_API}/sha256:${rel.sha256}`]: html } }).fetchImpl, keys: rel.keys });
  delete a.deps.attest;
  assert.equal(await run(['install', '--plan'], a.deps), EXIT.NETWORK);
  assert.match(a.output.err, /api\.github\.com answered with something that is not JSON/);
});

test('a corrupt sigstore cache is a preflight failure that names it, not a GitHub fault', async () => {
  const rel = release();
  const attestations = `${ATTESTATION_API}/sha256:${rel.sha256}`;
  const fetchImpl = async (url) => {
    if (url === attestations) return Response.json({ attestations: [{ bundle: { mediaType: 'application/vnd.dev.sigstore.bundle.v0.3+json' } }] });
    throw new Error(`unexpected fetch of ${url}`);
  };
  const h = await host({ fetchImpl, keys: rel.keys });
  delete h.deps.attest;
  const cache = join(h.root, 'cache', 'circuitbreaker', 'sigstore');
  await mkdir(join(cache, 'tuf-repo-cdn.sigstore.dev', 'targets'), { recursive: true });
  // tuf-js rewrites root.json in place; an interrupted write leaves it truncated.
  await writeFile(join(cache, 'tuf-repo-cdn.sigstore.dev', 'root.json'), '{"signed": {"_type": "ro');
  assert.equal(await run(['install', '--plan', '--json', '--local-bundle', await localBundle(rel)], h.deps), EXIT.PREFLIGHT);
  const { error } = JSON.parse(h.output.out);
  assert.equal(error.code, 'PREFLIGHT');
  assert.ok(error.reason.includes(cache), error.reason);
  assert.match(error.reason, /remove it and retry/);
  assert.doesNotMatch(h.output.err, /GitHub/);
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

test('an answer for an older unsigned release than the --version asked for is refused, not accepted as explicit', async () => {
  // The answer for tags/v0.4.8 claims to be v0.4.3, without a signature.
  const rel = release({ version: '0.4.3', signed: false });
  const answer = await (await github(rel).fetchImpl(`${RELEASE_API}/tags/v0.4.3`)).json();
  const gh = github(rel, { overrides: { [`${RELEASE_API}/tags/v0.4.8`]: () => Response.json(answer) } });
  const h = await host({ fetchImpl: gh.fetchImpl, keys: rel.keys });
  assert.equal(await run(['install', '--plan', '--json', '--version', '0.4.8'], h.deps), EXIT.TRUST, h.output.out);
  const { error } = JSON.parse(h.output.out);
  assert.equal(error.code, 'TRUST');
  assert.match(error.reason, /asked for release v0\.4\.8 .*answered with v0\.4\.3/);
  assert.doesNotMatch(h.output.err, /requested explicitly/);
  assert.deepEqual(gh.calls, [`${RELEASE_API}/tags/v0.4.8`], 'nothing is downloaded for an answer that is not trusted');
  await assert.rejects(stat(join(h.root, 'cache')), { code: 'ENOENT' }, 'nothing is staged');
});

test('a release tag that is not a version never names a staging path', async () => {
  // Deep enough that even the unguarded paths would stay inside this test's root.
  const rel = release({ version: '0.4.8/../../../../escaped' });
  const gh = github(rel);
  const h = await host({ fetchImpl: gh.fetchImpl, keys: rel.keys });
  h.deps.env.XDG_CACHE_HOME = join(h.root, 'a', 'b', 'c', 'd', 'cache');
  assert.equal(await run(['install', '--plan', '--channel', 'stable'], h.deps), EXIT.TRUST);
  assert.match(h.output.err, /not a release version/);
  assert.deepEqual(gh.calls, [`${RELEASE_API}?per_page=30`]);
  assert.deepEqual(await readdir(h.root, { recursive: true }), [], 'no directory or file was created');
});

test('an existing install is reported, and the plan says an install would be an update', async () => {
  const rel = release();
  const h = await host({ fetchImpl: github(rel).fetchImpl, keys: rel.keys, identity: { version: '0.4.6' } });
  assert.equal(await run(['install', '--plan'], h.deps), EXIT.OK, h.output.err);
  assert.match(h.output.out, /\nThis host already runs Circuit Breaker 0\.4\.6; an install would be an update\.\n$/);
  assert.doesNotMatch(h.output.out, /sub-plan/);

  const j = await host({ fetchImpl: github(rel).fetchImpl, keys: rel.keys, identity: { version: '0.4.6' } });
  assert.equal(await run(['install', '--plan', '--json'], j.deps), EXIT.OK, j.output.err);
  assert.deepEqual(JSON.parse(j.output.out).server, { version: '0.4.6', mode: 'native' });
});

// R4: the lifecycle result contract accepts what install --plan --json writes,
// including refusals that echo what the operator typed. Producers redact.
test('every --json result validates against the lifecycle result contract, hostile echoes included', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'cb-local-'));
  const cases = [
    [['--version', 'token=abcdef'], EXIT.USAGE, ['abcdef']],
    [['--version', 'api_key: abcdef'], EXIT.USAGE, ['abcdef']],
    [['--version', '0.4.7\u001b[31m'], EXIT.USAGE, ['\u001b']],
    [['--channel', 'x\u001b[2J\u009b31m'], EXIT.USAGE, ['\u001b', '\u009b']],
    [['--channel', 'http://admin:s3cret@proxy.lan'], EXIT.USAGE, ['s3cret']],
    [['--local-bundle', join(dir, 'token=abcdef', name('0.4.7'))], EXIT.USAGE, ['abcdef']],
    [['--local-bundle', join(dir, 'a\u0001x', name('0.4.7'))], EXIT.USAGE, ['\u0001']],
    [['--local-bundle', `${dir}/Bearer abcdefgh12345678/${name('0.4.7')}`], EXIT.USAGE, ['abcdefgh12345678']],
    // Fix round 2: the 4096-code-point cut lands right after `token=`, so the
    // bounded reason must not end in a credential shape (`token=…`).
    [['--version', `${'a'.repeat(4078)}token=  rest`], EXIT.USAGE, ['rest']],
    [['--channel', `${'a'.repeat(4069)}password:  rest`], EXIT.USAGE, ['rest']],
  ];
  for (const [argv, code, secrets] of cases) {
    const h = await host({ env: { CB_AIRGAP: 'true' } });
    assert.equal(await run(['install', '--plan', '--json', ...argv], h.deps), code, JSON.stringify(argv));
    const result = parseDocument('result', h.output.out.trimEnd());
    assert.equal(result.error.code, 'USAGE', JSON.stringify(argv));
    for (const secret of secrets) {
      assert.ok(!result.error.reason.includes(secret), `${JSON.stringify(argv)}: ${result.error.reason}`);
      assert.ok(!h.output.err.includes(secret), `${JSON.stringify(argv)} reached stderr unredacted: ${h.output.err}`);
    }
  }
  // An unknown option fails parsing before --json is known, so it has no
  // result (Task 4 pre-scans argv); its diagnostic is still redacted.
  const unknown = await host({ env: { CB_AIRGAP: 'true' } });
  assert.equal(await run(['install', '--plan', '--json', '--token=hunter2'], unknown.deps), EXIT.USAGE);
  assert.equal(unknown.output.out, '');
  assert.ok(!unknown.output.err.includes('hunter2'), unknown.output.err);

  const rel = release();
  const ok = await host({ fetchImpl: github(rel).fetchImpl, keys: rel.keys });
  assert.equal(await run(['install', '--plan', '--json', '--version', '0.4.7'], ok.deps), EXIT.OK, ok.output.err);
  assert.equal(parseDocument('result', ok.output.out.trimEnd()).outcome, 'verified');
  const untrusted = await host({ fetchImpl: github(release({ trusted: false })).fetchImpl, keys: rel.keys });
  assert.equal(await run(['install', '--plan', '--json'], untrusted.deps), EXIT.TRUST);
  assert.equal(parseDocument('result', untrusted.output.out.trimEnd()).error.code, 'TRUST');
});

test('a bundle path the result cannot carry is refused before verification, never reported altered', async () => {
  const rel = release();
  const parent = await mkdtemp(join(tmpdir(), 'cb-local-'));
  for (const odd of ['line\nbreak', 'csi\u009bx', 'esc\u001b[31m']) {
    const dir = join(parent, odd);
    await mkdir(dir);
    for (const [file, bytes] of [[name('0.4.7'), rel.tarball], ['SHA256SUMS', rel.sums], ['SHA256SUMS.sig', rel.sig]]) {
      await writeFile(join(dir, file), bytes);
    }
    const h = await host({ keys: rel.keys, env: { CB_AIRGAP: 'true' } });
    assert.equal(await run(['install', '--plan', '--json', '--local-bundle', join(dir, name('0.4.7'))], h.deps), EXIT.USAGE, JSON.stringify(odd));
    const result = parseDocument('result', h.output.out.trimEnd());
    assert.match(result.error.reason, /control character/);
    assert.ok(!h.output.err.includes(odd), JSON.stringify(h.output.err));
  }
});

test('an installed version the result cannot carry as is is reported escaped', async () => {
  const rel = release();
  for (const [version, reported] of [['latest', 'latest'], ['unknown', 'unknown'], ['0.4.6\u001b[31m', '0.4.6\\u001b[31m'], ['v'.repeat(70), `${'v'.repeat(63)}…`]]) {
    const h = await host({ fetchImpl: github(rel).fetchImpl, keys: rel.keys, identity: { version } });
    assert.equal(await run(['install', '--plan', '--json'], h.deps), EXIT.OK, h.output.err);
    assert.deepEqual(parseDocument('result', h.output.out.trimEnd()).server, { version: reported, mode: 'native' });
  }
});

test('help lists install --plan under this CLI and says host-changing installs come later', async () => {
  const h = await host();
  assert.equal(await run(['help'], h.deps), EXIT.OK);
  assert.match(h.output.out, /This CLI:\n {2}install --plan +Resolve, download and verify a release; changes nothing \[--json\]\n/);
  assert.match(h.output.out, /\nInstall, update and uninstall that change the host arrive in later builds; `install --plan` shows what an install would do\.\n/);
});
