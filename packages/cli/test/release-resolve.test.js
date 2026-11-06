import { test } from 'node:test';
import assert from 'node:assert/strict';
import { resolveTarget, debArch, RELEASE_API } from '../src/release-resolve.js';

const asset = (id, name, size = 10) => ({ id, name, size, browser_download_url: `https://dl/${name}` });
const release = (tag, { draft = false, prerelease = false, sig = true } = {}) => {
  const v = tag.replace(/^v/, '');
  return {
    tag_name: tag, draft, prerelease,
    assets: [asset(1, `circuit-breaker_${v}_linux_amd64.tar.gz`, 100), asset(2, 'SHA256SUMS'), ...(sig ? [asset(3, 'SHA256SUMS.sig')] : [])],
  };
};
const api = (routes) => async (url) => {
  if (!(url in routes)) { const e = new Error('404'); e.status = 404; e.code = 'HTTP_STATUS'; throw e; }
  return routes[url];
};

test('the default target is the CLI version, fetched by tag', async () => {
  const t = await resolveTarget({ cliVersion: '0.4.7', arch: 'amd64', fetchJson: api({ [`${RELEASE_API}/tags/v0.4.7`]: release('v0.4.7') }) });
  assert.equal(t.version, '0.4.7');
  assert.equal(t.explicitVersion, false);
  assert.deepEqual(t.tarball, { id: 1, name: 'circuit-breaker_0.4.7_linux_amd64.tar.gz', size: 100, url: 'https://dl/circuit-breaker_0.4.7_linux_amd64.tar.gz' });
  assert.equal(t.sig.name, 'SHA256SUMS.sig');
});

test('--version is explicit and strips one leading v', async () => {
  const t = await resolveTarget({ version: 'v0.4.3', cliVersion: '0.4.7', arch: 'amd64', fetchJson: api({ [`${RELEASE_API}/tags/v0.4.3`]: release('v0.4.3', { sig: false }) }) });
  assert.equal(t.version, '0.4.3');
  assert.equal(t.explicitVersion, true);
  assert.equal(t.sig, null);
});

test('channels pick the newest eligible release from the list', async () => {
  const list = [release('v0.5.0-rc.1', { prerelease: true }), release('v0.4.9', { draft: true }), release('v0.4.8')];
  const f = api({ [`${RELEASE_API}?per_page=30`]: list });
  assert.equal((await resolveTarget({ channel: 'stable', cliVersion: '0.4.7', arch: 'amd64', fetchJson: f })).version, '0.4.8');
  assert.equal((await resolveTarget({ channel: 'candidate', cliVersion: '0.4.7', arch: 'amd64', fetchJson: f })).version, '0.5.0-rc.1');
});

test('usage and unsupported errors are distinct', async () => {
  const f = api({});
  await assert.rejects(resolveTarget({ version: '0.4.7', channel: 'stable', cliVersion: '0.4.7', arch: 'amd64', fetchJson: f }), { code: 'USAGE' });
  await assert.rejects(resolveTarget({ channel: 'nightly', cliVersion: '0.4.7', arch: 'amd64', fetchJson: f }), { code: 'USAGE' });
  await assert.rejects(resolveTarget({ cliVersion: '0.4.7', arch: null, fetchJson: f }), { code: 'UNSUPPORTED' });
  await assert.rejects(resolveTarget({ cliVersion: '0.4.7', arch: 'amd64', fetchJson: f }), { code: 'UNSUPPORTED' });
  const noArm = api({ [`${RELEASE_API}/tags/v0.4.7`]: release('v0.4.7') });
  await assert.rejects(resolveTarget({ cliVersion: '0.4.7', arch: 'arm64', fetchJson: noArm }), { code: 'UNSUPPORTED' });
});

test('the target records the version the operator asked for, and only that', async () => {
  const f = api({
    [`${RELEASE_API}/tags/v0.4.3`]: release('v0.4.3', { sig: false }),
    [`${RELEASE_API}/tags/v0.4.7`]: release('v0.4.7'),
    [`${RELEASE_API}?per_page=30`]: [release('v0.4.8')],
  });
  assert.equal((await resolveTarget({ version: 'v0.4.3', cliVersion: '0.4.7', arch: 'amd64', fetchJson: f })).requestedVersion, '0.4.3');
  assert.equal((await resolveTarget({ cliVersion: '0.4.7', arch: 'amd64', fetchJson: f })).requestedVersion, null);
  assert.equal((await resolveTarget({ channel: 'stable', cliVersion: '0.4.7', arch: 'amd64', fetchJson: f })).requestedVersion, null);
});

test('an answer naming another release than the tag asked for is not trusted', async () => {
  // GitHub answers tags/vX with tag_name vX; anything else is not its answer.
  const older = release('v0.4.3', { sig: false });
  const explicit = api({ [`${RELEASE_API}/tags/v0.4.8`]: older });
  await assert.rejects(resolveTarget({ version: '0.4.8', cliVersion: '0.4.7', arch: 'amd64', fetchJson: explicit }),
    { code: 'TRUST', message: /asked for release v0\.4\.8 .*answered with v0\.4\.3/ });
  const byDefault = api({ [`${RELEASE_API}/tags/v0.4.7`]: release('v0.4.6') });
  await assert.rejects(resolveTarget({ cliVersion: '0.4.7', arch: 'amd64', fetchJson: byDefault }),
    { code: 'TRUST', message: /asked for release v0\.4\.7 .*answered with v0\.4\.6/ });
});

test('a tag that is not a release version is refused before it names any file, on every path', async () => {
  const escape = 'v0.4.8/../../../../escaped';
  for (const tag of [escape, 'vv0.4.8', '0.4.8\u001b[2J', '', null, 48]) {
    const bad = {
      tag_name: tag, draft: false, prerelease: false,
      assets: [asset(1, `circuit-breaker_${String(tag).replace(/^v/, '')}_linux_amd64.tar.gz`, 100), asset(2, 'SHA256SUMS'), asset(3, 'SHA256SUMS.sig')],
    };
    const f = api({ [`${RELEASE_API}?per_page=30`]: [bad] });
    await assert.rejects(resolveTarget({ channel: 'candidate', cliVersion: '0.4.7', arch: 'amd64', fetchJson: f }),
      (error) => error.code === 'TRUST' && /not a release version/.test(error.message) && !/[^\x20-\x7e]/.test(error.message),
      String(tag));
  }
});

test('a --version that is not a release version is refused before any request', async () => {
  const calls = [];
  const f = async (url) => { calls.push(url); throw new Error(`unexpected fetch of ${url}`); };
  for (const version of ['../../evil', '', 'vv0.4.8', '0.4.8?x=1']) {
    await assert.rejects(resolveTarget({ version, cliVersion: '0.4.7', arch: 'amd64', fetchJson: f }), { code: 'USAGE' }, version);
  }
  assert.deepEqual(calls, []);
});

test('architectures map like install.sh', () => {
  assert.equal(debArch('x64'), 'amd64');
  assert.equal(debArch('arm64'), 'arm64');
  assert.equal(debArch('ia32'), null);
});
