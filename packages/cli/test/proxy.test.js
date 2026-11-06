import { test } from 'node:test';
import assert from 'node:assert/strict';
import { proxyReexec } from '../src/proxy.js';

test('no proxy variables means no re-exec', () => {
  assert.equal(proxyReexec({}, '/n', ['/n', '/cli.js', 'status']), null);
});

test('a proxy variable re-execs once with NODE_USE_ENV_PROXY=1 and the same arguments', () => {
  for (const name of ['HTTPS_PROXY', 'HTTP_PROXY', 'https_proxy', 'http_proxy']) {
    const plan = proxyReexec({ [name]: 'http://proxy:3128' }, '/usr/bin/node', ['/usr/bin/node', '/cli.js', 'install', '--plan']);
    assert.deepEqual(plan, {
      command: '/usr/bin/node',
      args: ['/cli.js', 'install', '--plan'],
      env: { [name]: 'http://proxy:3128', NODE_USE_ENV_PROXY: '1' },
    }, name);
  }
});

test('already re-executed means no loop', () => {
  assert.equal(proxyReexec({ HTTPS_PROXY: 'http://p', NODE_USE_ENV_PROXY: '1' }, '/n', ['/n', '/c']), null);
});
