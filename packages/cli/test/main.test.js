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
import { parseDocument } from '../src/lifecycle-contract.js';

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
  for (const name of ['uninstall']) {
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

test('identity read errors in help become EXIT.UNSUPPORTED', async () => {
  const { deps, output } = await host({ identity: {} });
  deps.readFile = async () => { throw Object.assign(new Error('symlink loop'), { code: 'ELOOP' }); };
  assert.equal(await run(['help'], deps), EXIT.UNSUPPORTED);
  assert.match(output.err, /ELOOP/);
});

test('identity read errors in version become EXIT.UNSUPPORTED', async () => {
  const { deps, output } = await host({ identity: {} });
  deps.readFile = async () => { throw Object.assign(new Error('symlink loop'), { code: 'ELOOP' }); };
  assert.equal(await run(['version'], deps), EXIT.UNSUPPORTED);
  assert.match(output.err, /ELOOP/);
});

test('identity read errors during forwarding become EXIT.UNSUPPORTED', async () => {
  const { deps, output } = await host({ identity: {} });
  deps.readFile = async () => { throw Object.assign(new Error('symlink loop'), { code: 'ELOOP' }); };
  assert.equal(await run(['status'], deps), EXIT.UNSUPPORTED);
  assert.match(output.err, /ELOOP/);
});

function rootFakes(files) {
  // files: resolved path -> text. Fake fs where every judged entry is a root-owned 0644 file.
  const calls = { readFile: [], realpath: [], stat: [] };
  const info = (isFile) => ({ uid: 0, mode: isFile ? 0o100644 : 0o040755, isFile: () => isFile });
  return {
    calls,
    realpath: async (p) => { calls.realpath.push(p); return p; },
    stat: async (p) => { calls.stat.push(p); return info(p in files); },
    readFile: async (p) => { calls.readFile.push(p); if (p in files) return files[p]; throw Object.assign(new Error('x'), { code: 'ENOENT' }); },
  };
}

test('as root, the bytes read are those of the resolved path that was trust-checked', async () => {
  const { deps } = await host({ identity: {} });
  const good = JSON.stringify({ schema_version: 1, mode: 'native', version: '0.4.7', installed_at: '2026-09-30T00:00:00Z' });
  const fakes = rootFakes({ '/etc/circuitbreaker/checked.json': good });
  let n = 0;
  deps.euid = 0;
  deps.trustedUids = [0];
  deps.env = { PATH: '', CB_IDENTITY_PATH: '/home/u/.circuit-breaker/install-identity.json' };
  deps.stat = fakes.stat;
  deps.readFile = fakes.readFile;
  deps.realpath = async (p) => { fakes.calls.realpath.push(p); n += 1; return n === 1 ? '/etc/circuitbreaker/checked.json' : '/home/u/evil.json'; };
  const { output } = { output: { out: '' } };
  deps.out = (t) => { output.out += t; };
  assert.equal(await run(['version', '--json'], deps), EXIT.OK);
  assert.deepEqual(fakes.calls.readFile, ['/etc/circuitbreaker/checked.json']);
  assert.equal(JSON.parse(output.out).identity_path, '/home/u/.circuit-breaker/install-identity.json');
});

test('as root, help and version show an untrusted identity as status untrusted', async () => {
  const { deps, output } = await host({ identity: {} });
  deps.euid = 0;
  deps.trustedUids = [0];
  assert.equal(await run(['version', '--json'], deps), EXIT.OK);
  assert.equal(JSON.parse(output.out).identity, 'untrusted');
  output.out = '';
  assert.equal(await run(['help'], deps), EXIT.OK);
  assert.match(output.out, /Identity: untrusted/);
});

test('as root, a missing first candidate still finds a trusted second candidate', async () => {
  const { deps, output } = await host({ identity: {} });
  const good = JSON.stringify({ schema_version: 1, mode: 'native', version: '0.4.7', installed_at: '2026-09-30T00:00:00Z' });
  const fakes = rootFakes({ '/etc/circuit-breaker/install-identity.json': good });
  deps.euid = 0;
  deps.env = { PATH: '' };
  deps.home = undefined;
  deps.stat = fakes.stat;
  deps.readFile = fakes.readFile;
  deps.realpath = async (p) => {
    if (p === '/etc/circuitbreaker/install-identity.json') throw Object.assign(new Error('gone'), { code: 'ENOENT' });
    return p;
  };
  assert.equal(await run(['version', '--json'], deps), EXIT.OK);
  assert.equal(JSON.parse(output.out).identity, 'found');
  assert.deepEqual(fakes.calls.readFile, ['/etc/circuit-breaker/install-identity.json']);
});

test('a non-root run never trust-checks the identity file', async () => {
  const { deps, identityPath } = await host({ identity: {} });
  const seen = [];
  deps.realpath = async (p) => { seen.push(p); return realpath(p); };
  assert.equal(await run(['status'], deps), EXIT.OK);
  assert.ok(!seen.includes(identityPath), 'identity path must not be realpath-checked');
});

// --- Machine streams (lifecycle contract §7, ruling R16).

const eventLines = (text) => {
  assert.ok(text.endsWith('\n'), JSON.stringify(text));
  return text.slice(0, -1).split('\n').map((line) => parseDocument('event', line));
};

test('with --events=jsonl every refusal main makes is a framed, redacted diagnostic', async () => {
  for (const [argv, code, echo] of [
    [['rm', '--events=jsonl', 'token=hunter2'], EXIT.USAGE, null],
    [['token=hunter2', '--events=jsonl'], EXIT.USAGE, 'hunter2'],
    [['update', '--events', 'jsonl'], EXIT.USAGE, null],
    [['history', '--events=jsonl'], EXIT.USAGE, null],
    [['version', '--events=jsonl'], EXIT.USAGE, null],
  ]) {
    const { deps, output } = await host({ identity: {} });
    assert.equal(await run(argv, deps), code, argv.join(' '));
    const [diagnostic, ...rest] = eventLines(output.err);
    assert.deepEqual(rest, [], argv.join(' '));
    assert.equal(diagnostic.type, 'diagnostic');
    assert.equal(diagnostic.level, 'error');
    if (echo) assert.ok(!diagnostic.message.includes(echo), diagnostic.message);
    assert.equal(output.out, '');
  }
});

test('a loop refusal is framed too, before anything else runs', async () => {
  const { deps, output } = await host({ identity: {} });
  deps.env.CIRCUITBREAKER_FORWARDED = '1';
  assert.equal(await run(['install', '--plan', '--events=jsonl'], deps), EXIT.USAGE);
  assert.deepEqual(eventLines(output.err).map((e) => [e.type, e.code]), [['diagnostic', 'USAGE']]);
});

test('--events takes only jsonl', async () => {
  for (const argv of [['install', '--plan', '--events=yaml'], ['history', '--events'], ['install', '--plan', '--json', '--events', 'text']]) {
    const { deps, output } = await host({ identity: {} });
    assert.equal(await run(argv, deps), EXIT.USAGE, argv.join(' '));
    assert.match(output.err, /^circuitbreaker: --events takes jsonl/);
    if (argv.includes('--json')) assert.equal(parseDocument('result', output.out.trimEnd()).error.code, 'USAGE');
    else assert.equal(output.out, '');
  }
});

test('forwarded management arguments are never read as stream flags', async () => {
  for (const args of [['logs', '--events=jsonl', '--json'], ['status', '--events=yaml', '--json']]) {
    const { deps, output } = await host({ identity: {} });
    assert.equal(await run(args, deps), EXIT.OK, args.join(' '));
    assert.deepEqual(JSON.parse(await readFile(deps.env.OUT, 'utf8')), args);
    assert.deepEqual(output, { out: '', err: '' });
  }
});

test('an injected result writer and event writer receive what the run produces', async () => {
  const { deps } = await host({ identity: {} });
  const written = [];
  const framed = [];
  deps.result = { written: false, write(doc) { written.push(doc); this.written = true; } };
  deps.events = { diagnostic: (message, options) => framed.push([message, options?.code]) };
  deps.env.CB_LIFECYCLE_ROOT = '/nonexistent-lifecycle-root';
  assert.equal(await run(['history', '--json'], deps), EXIT.OK);
  assert.deepEqual(written, [{ schema_version: 1, action: 'history', outcome: 'listed', operations: [] }]);
  assert.equal(await run(['history', '--json', '--events=jsonl'], deps), EXIT.USAGE);
  assert.equal(framed.length, 1);
  assert.equal(framed[0][1], 'USAGE');
});

test('help lists history and says where each machine stream goes', async () => {
  const { deps, output } = await host({ identity: {} });
  assert.equal(await run(['help'], deps), EXIT.OK);
  assert.match(output.out, /\n {2}history +Lifecycle operations recorded on this host; read-only \[--json\]\n/);
  assert.match(output.out, /\nMachine output: --json prints one final JSON result on stdout; install --plan --events=jsonl writes JSONL events, and nothing else, on stderr\.\n/);
});
