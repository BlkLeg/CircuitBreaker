#!/usr/bin/env node
// Called only by release.yml's protected promotion job. Never repacks source.
import { createHash } from 'node:crypto';
import { readFile, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';

const REGISTRY = 'https://registry.npmjs.org/';
const NAME = '@blkleg/circuitbreaker';
export const integrity = (bytes) => `sha512-${createHash('sha512').update(bytes).digest('base64')}`;

function npm(args, cwd) {
  try { return execFileSync('npm', [...args, `--registry=${REGISTRY}`, '--fetch-timeout=30000', '--fetch-retries=2'], { cwd, encoding: 'utf8', timeout: 180_000, maxBuffer: 8 * 1024 * 1024 }); }
  catch (error) {
    let response;
    try { response = JSON.parse(error.stdout); } catch { /* npm did not return JSON */ }
    if (response?.error?.code === 'E404') throw Object.assign(new Error('version not found'), { code: 'E404' });
    throw new Error(`npm ${args[0]} failed (exit ${error.status ?? 'timeout'}); publication gate stopped`);
  }
}

export async function publishExact({ tarball, version, tag = 'latest', runNpm = npm, inspect, evidencePath }) {
  if (!/^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/.test(version)) throw Error('invalid release version');
  if (!['latest', 'next'].includes(tag)) throw Error('invalid npm release tag');
  const path = resolve(tarball);
  const bytes = await readFile(path);
  const expected = integrity(bytes);
  const manifest = inspect ? await inspect(path) : JSON.parse(execFileSync('tar', ['-xOf', path, 'package/package.json'], { encoding: 'utf8', timeout: 30_000, maxBuffer: 1024 * 1024 }));
  if (manifest.name !== NAME || manifest.version !== version || manifest.private !== false) throw Error('tarball manifest does not match the publishable CLI release');
  if (manifest.repository?.url !== 'git+https://github.com/BlkLeg/CircuitBreaker.git') throw Error('unexpected package repository');
  if (['preinstall', 'install', 'postinstall', 'prepare', 'prepack', 'postpack', 'prepublish', 'prepublishOnly', 'publish', 'postpublish'].some((key) => manifest.scripts?.[key])) throw Error('CLI tarball contains an npm lifecycle hook');
  const spec = `${NAME}@${version}`;
  let existing = null;
  try { existing = JSON.parse(await runNpm(['view', spec, 'dist', '--json'])); }
  catch (error) { if (error.code !== 'E404') throw error; }
  if (existing && existing.integrity !== expected) throw Error('npm version exists with different bytes; never overwrite or promote it');
  if (!existing) await runNpm(['publish', path, '--ignore-scripts', '--provenance', '--access=public', '--tag=cb-verified']);
  const work = await mkdtemp(join(tmpdir(), 'cb-registry-check-'));
  try {
    const dist = JSON.parse(await runNpm(['view', spec, 'dist', '--json']));
    if (dist.integrity !== expected) throw Error('published npm integrity differs from the accepted tarball');
    if (!dist.attestations?.url) throw Error('published package has no provenance attestation');
    const packed = JSON.parse(await runNpm(['pack', spec, '--ignore-scripts', '--prefer-online', '--json', '--pack-destination', work]));
    if (!Array.isArray(packed) || packed.length !== 1 || !/^[A-Za-z0-9._-]+\.tgz$/.test(packed[0].filename)) throw Error('npm pack returned an unsafe filename');
    const fetched = await readFile(join(work, packed[0].filename));
    if (integrity(fetched) !== expected) throw Error('registry round-trip bytes differ from the accepted tarball');
    // npm verifies registry signatures and Sigstore provenance on installed bytes.
    await runNpm(['install', '--ignore-scripts', '--no-audit', '--no-fund', '--prefix', work, spec]);
    await runNpm(['audit', 'signatures', '--prefix', work]);
    await runNpm(['dist-tag', 'add', spec, tag]);
    const evidence = { schema_version: 1, package: NAME, version, tag, sha256: createHash('sha256').update(bytes).digest('hex'), integrity: expected, provenance: dist.attestations.url, registry_round_trip: 'verified', commit: process.env.GITHUB_SHA ?? null };
    if (evidencePath) await writeFile(evidencePath, `${JSON.stringify(evidence, null, 2)}\n`);
    return evidence;
  } finally { await rm(work, { recursive: true, force: true }); }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const [tarball, version, tag, evidencePath] = process.argv.slice(2);
  if (!tarball || !version || !evidencePath) { console.error('usage: cli_publish.mjs TARBALL VERSION latest|next EVIDENCE.json'); process.exitCode = 2; }
  else {
    try { console.log(JSON.stringify(await publishExact({ tarball, version, tag, evidencePath }))); }
    catch (error) { console.error(`CLI publication refused: ${error.message}`); process.exitCode = 1; }
  }
}
