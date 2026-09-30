import { test } from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { mkdtemp, writeFile, chmod, readFile } from 'node:fs/promises';
import { readFile as fsReadFile, stat, realpath } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { run } from '../src/main.js';
import { EXIT } from '../src/exit-codes.js';
import { NATIVE_COMMANDS } from '../src/inventory.js';

async function host({ identity, cbBody = "require('node:fs').writeFileSync(process.env.OUT, JSON.stringify(process.argv.slice(2)));" } = {}) {
  const dir = await mkdtemp(join(tmpdir(), 'cb-main-'));
  const cb = join(dir, 'cb');
  await writeFile(cb, `#!/usr/bin/env node\n${cbBody}\n`);
  await chmod(cb, 0o755);
  const identityPath = join(dir, 'install-identity.json');
  if (identity !== null) {
    await writeFile(identityPath, JSON.stringify({
      schema_version: 1, mode: 'native', version: '0.4.7', installed_at: '2026-09-30T00:00:00Z', cli_path: cb, ...identity,
    }));
  }
  const output = { out: '', err: '' };
  const deps = {
    env: { PATH: process.env.PATH, CB_IDENTITY_PATH: identityPath, OUT: join(dir, 'argv.json') },
    home: dir,
    euid: process.geteuid(),
    out: (t) => { output.out += t; },
    err: (t) => { output.err += t; },
    readFile: fsReadFile, stat, realpath, spawnImpl: spawn,
    proc: new EventEmitter(),
    trustedUids: [process.getuid()],
    cliVersion: '0.4.7',
  };
  return { dir, cb, identityPath, deps, output };
}

test('help lists every non-lifecycle management command and exits 0', async () => {
  const { deps, output } = await host({ identity: {} });
  assert.equal(await run(['help'], deps), EXIT.OK);
  for (const c of NATIVE_COMMANDS.filter((c) => !c.lifecycle)) assert.match(output.out, new RegExp(`\\b${c.name}\\b`));
  assert.match(output.out, /Identity: .*install-identity\.json/);
  assert.equal(await run([], deps), EXIT.OK, 'no arguments means help');
  assert.equal(await run(['--help'], deps), EXIT.OK);
});

test('help still works when identity is missing', async () => {
  const { deps, output } = await host({ identity: null });
  assert.equal(await run(['-h'], deps), EXIT.OK);
  assert.match(output.out, /Identity: missing/);
});

test('management commands forward verbatim and return the child code', async () => {
  const { deps } = await host({ identity: {} });
  assert.equal(await run(['logs', '-f', '$(id)'], deps), EXIT.OK);
  assert.deepEqual(JSON.parse(await readFile(deps.env.OUT, 'utf8')), ['logs', '-f', '$(id)']);
  const failing = await host({ identity: {}, cbBody: 'process.exit(3);' });
  assert.equal(await run(['migrate', 'status'], failing.deps), 3);
});

test('unknown commands are usage errors', async () => {
  const { deps, output } = await host({ identity: {} });
  assert.equal(await run(['rm'], deps), EXIT.USAGE);
  assert.match(output.err, /unknown command 'rm'/);
});

test('lifecycle commands are refused, not forwarded', async () => {
  for (const name of ['update', 'uninstall']) {
    const { deps, output } = await host({ identity: {} });
    assert.equal(await run([name], deps), EXIT.UNSUPPORTED);
    assert.match(output.err, new RegExp(`cb ${name}`));
    await assert.rejects(readFile(deps.env.OUT, 'utf8'), { code: 'ENOENT' });
  }
});

test('a forwarding loop is refused before anything else', async () => {
  const { deps, output } = await host({ identity: {} });
  deps.env.CIRCUITBREAKER_FORWARDED = '1';
  assert.equal(await run(['status'], deps), EXIT.USAGE);
  assert.match(output.err, /forwarding loop/);
});

test('missing identity is a diagnosis naming the searched paths, never a guess', async () => {
  const { deps, output, identityPath } = await host({ identity: null });
  assert.equal(await run(['status'], deps), EXIT.UNSUPPORTED);
  assert.match(output.err, new RegExp(identityPath));
  assert.match(output.err, /install\.sh/);
});

test('unreadable identity is a permission error', async () => {
  const { deps, output } = await host({ identity: {} });
  deps.readFile = async () => { throw Object.assign(new Error('denied'), { code: 'EACCES' }); };
  assert.equal(await run(['status'], deps), EXIT.PERMISSION);
  assert.match(output.err, /sudo/);
});

test('invalid identity lists the problems', async () => {
  const { deps, output } = await host({ identity: { mode: 'k8s' } });
  assert.equal(await run(['status'], deps), EXIT.UNSUPPORTED);
  assert.match(output.err, /mode/);
});

test('identity without cli_path cannot be forwarded', async () => {
  const { deps, identityPath, output } = await host({ identity: {} });
  const doc = JSON.parse(await readFile(identityPath, 'utf8'));
  delete doc.cli_path;
  await writeFile(identityPath, JSON.stringify(doc));
  assert.equal(await run(['status'], deps), EXIT.UNSUPPORTED);
  assert.match(output.err, /cli_path/);
});

test('an untrusted cli_path is a trust failure', async () => {
  const { deps, cb, output } = await host({ identity: {} });
  await chmod(cb, 0o777);
  assert.equal(await run(['status'], deps), EXIT.TRUST);
  assert.match(output.err, /writable by group or others/);
});

test('as root, an identity file root does not own is refused', async () => {
  const { deps, output } = await host({ identity: {} });
  deps.euid = 0;
  deps.trustedUids = [0];
  assert.equal(await run(['status'], deps), EXIT.TRUST);
  assert.match(output.err, /install-identity\.json/);
});

test('an uncertified server version is refused for management', async () => {
  const { deps, output } = await host({ identity: { version: '0.3.0' } });
  assert.equal(await run(['status'], deps), EXIT.UNSUPPORTED);
  assert.match(output.err, /0\.3\.0/);
});

test('version reports CLI and server separately, in text and JSON', async () => {
  const { deps, output, cb, identityPath } = await host({ identity: { version: '0.4.6' } });
  assert.equal(await run(['version'], deps), EXIT.OK);
  assert.match(output.out, /CLI\s+0\.4\.7/);
  assert.match(output.out, /Server\s+0\.4\.6 \(native\)/);
  output.out = '';
  assert.equal(await run(['--version', '--json'], deps), EXIT.OK);
  assert.deepEqual(JSON.parse(output.out), {
    schema_version: 1,
    cli_version: '0.4.7',
    identity: 'found',
    identity_path: identityPath,
    server: { version: '0.4.6', mode: 'native', cli_path: cb },
    compatibility: { certified: true, reason: 'certified for management by this CLI' },
  });
});

test('version without an install still answers, with a null server', async () => {
  const { deps, output } = await host({ identity: null });
  assert.equal(await run(['version', '--json'], deps), EXIT.OK);
  const report = JSON.parse(output.out);
  assert.equal(report.server, null);
  assert.equal(report.identity, 'missing');
});

test('version rejects unknown options', async () => {
  const { deps } = await host({ identity: {} });
  assert.equal(await run(['version', '--yaml'], deps), EXIT.USAGE);
});
