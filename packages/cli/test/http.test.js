import { test } from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import net from 'node:net';
import { spawn } from 'node:child_process';
import { fetchJson, fetchBytes, request, NetworkError, HttpStatusError, USER_AGENT } from '../src/http.js';

const okFetch = (body, status = 200) => async () => new Response(JSON.stringify(body), { status });

// NODE_USE_ENV_PROXY exists from Node 22.21 and 24.0; it is absent on 23.x and older lines.
function supportsEnvProxy(version) {
  const [major, minor] = version.split('.').map(Number);
  if (major === 22) return minor >= 21;
  return major >= 24;
}

test('fetchJson returns parsed JSON and sends the CLI user agent', async () => {
  let seen;
  const fetchImpl = async (url, init) => { seen = init; return new Response('{"a":1}', { status: 200 }); };
  assert.deepEqual(await fetchJson('https://x/y', { fetchImpl }), { a: 1 });
  assert.equal(seen.headers['user-agent'], USER_AGENT);
  assert.match(USER_AGENT, /^circuitbreaker-cli\/\d+\.\d+\.\d+/);
});

test('non-2xx is an HttpStatusError with its status', async () => {
  await assert.rejects(fetchJson('https://x', { fetchImpl: okFetch({}, 404) }), (e) => e instanceof HttpStatusError && e.status === 404);
});

test('transport failures and timeouts are NetworkError', async () => {
  const boom = async () => { throw new TypeError('fetch failed'); };
  await assert.rejects(fetchJson('https://x', { fetchImpl: boom }), (e) => e instanceof NetworkError && e.code === 'NETWORK');
  const hang = (url, init) => new Promise((resolve, reject) => init.signal.addEventListener('abort', () => reject(init.signal.reason)));
  await assert.rejects(fetchJson('https://x', { fetchImpl: hang, timeoutMs: 50 }), (e) => e instanceof NetworkError);
});

// Headers arrive at once; the body then waits `stallMs` before its chunk, and errors if the request signal aborts.
const stallingFetch = (stallMs, text) => async (url, init) => new Response(new ReadableStream({
  start(controller) {
    const timer = setTimeout(() => { controller.enqueue(new TextEncoder().encode(text)); controller.close(); }, stallMs);
    init.signal.addEventListener('abort', () => { clearTimeout(timer); controller.error(init.signal.reason); });
  },
}), { status: 200 });

test("request's timer stops at the headers: a slow body is not aborted by it", async () => {
  const response = await request('https://x', { fetchImpl: stallingFetch(150, '{"a":1}'), timeoutMs: 50 });
  assert.deepEqual(await response.json(), { a: 1 });
});

test('fetchJson bounds the body read and reports a stalled body as NetworkError', async () => {
  await assert.rejects(fetchJson('https://x', { fetchImpl: stallingFetch(1000, '{}'), timeoutMs: 50 }),
    (e) => e instanceof NetworkError && e.code === 'NETWORK');
});

test('fetchJson leaves invalid JSON as a SyntaxError', async () => {
  await assert.rejects(fetchJson('https://x', { fetchImpl: stallingFetch(0, 'nope') }), SyntaxError);
});

test('fetchBytes returns the raw body without the GitHub accept header', async () => {
  let seen;
  const fetchImpl = async (url, init) => { seen = init; return new Response(Buffer.from([0x89, 0x32, 0xf0])); };
  const body = await fetchBytes('https://blob/x', { fetchImpl });
  assert.ok(Buffer.isBuffer(body));
  assert.deepEqual([...body], [0x89, 0x32, 0xf0]);
  assert.equal(seen.headers.accept, undefined);
  assert.equal(seen.headers['user-agent'], USER_AGENT);
});

test('fetchBytes maps HTTP, transport and stall failures like fetchJson', async () => {
  await assert.rejects(fetchBytes('https://x', { fetchImpl: okFetch({}, 403) }), (e) => e instanceof HttpStatusError && e.status === 403);
  await assert.rejects(fetchBytes('https://x', { fetchImpl: async () => { throw new TypeError('fetch failed'); } }), (e) => e instanceof NetworkError);
  await assert.rejects(fetchBytes('https://x', { fetchImpl: stallingFetch(1000, 'x'), timeoutMs: 50 }), (e) => e instanceof NetworkError);
});

test('fetchBytes refuses a body larger than maxBytes, declared or streamed', async () => {
  const declared = async () => new Response('0123456789', { headers: { 'content-length': '10' } });
  await assert.rejects(fetchBytes('https://x', { fetchImpl: declared, maxBytes: 4 }), (e) => e instanceof NetworkError && /more than 4 bytes/.test(e.message));
  const undeclared = async () => new Response(new ReadableStream({
    start(c) { c.enqueue(new TextEncoder().encode('0123')); c.enqueue(new TextEncoder().encode('4567')); c.close(); },
  }));
  await assert.rejects(fetchBytes('https://x', { fetchImpl: undeclared, maxBytes: 6 }), (e) => e instanceof NetworkError && /more than 6 bytes/.test(e.message));
  assert.equal((await fetchBytes('https://x', { fetchImpl: undeclared, maxBytes: 8 })).toString(), '01234567');
});

test('with NODE_USE_ENV_PROXY=1 and HTTP_PROXY set, requests go through the proxy', async (t) => {
  if (!supportsEnvProxy(process.versions.node)) {
    t.skip(`Node ${process.versions.node} lacks NODE_USE_ENV_PROXY; needs 22.21+ or 24+`);
    return;
  }
  const target = http.createServer((req, res) => { res.setHeader('content-type', 'application/json'); res.end('{"via":"target"}'); });
  // Records every request that reaches it as host:port. Node 22.23 tunnels even
  // plain-HTTP targets through CONNECT; other versions may send absolute-URI
  // forward requests, so the proxy serves both.
  const proxied = [];
  const proxy = http.createServer((req, res) => {
    const { host } = new URL(req.url);
    proxied.push(host);
    const upstream = http.request(req.url, { method: req.method, headers: req.headers }, (up) => { res.writeHead(up.statusCode, up.headers); up.pipe(res); });
    req.pipe(upstream);
  });
  proxy.on('connect', (req, clientSocket, head) => {
    proxied.push(req.url);
    const [host, port] = req.url.split(':');
    const upstream = net.connect(Number(port), host, () => {
      clientSocket.write('HTTP/1.1 200 Connection Established\r\n\r\n');
      upstream.write(head);
      upstream.pipe(clientSocket);
      clientSocket.pipe(upstream);
    });
    upstream.on('error', () => clientSocket.destroy());
    clientSocket.on('error', () => upstream.destroy());
  });
  await Promise.all([new Promise((r) => target.listen(0, '127.0.0.1', r)), new Promise((r) => proxy.listen(0, '127.0.0.1', r))]);
  t.after(() => { target.close(); proxy.close(); });
  const targetHost = `127.0.0.1:${target.address().port}`;
  const url = `http://${targetHost}/x`;
  const child = spawn(process.execPath, ['--input-type=module', '-e',
    `import { fetchJson } from ${JSON.stringify(new URL('../src/http.js', import.meta.url).href)}; console.log(JSON.stringify(await fetchJson(${JSON.stringify(url)})));`],
    { env: { PATH: process.env.PATH, NODE_USE_ENV_PROXY: '1', HTTP_PROXY: `http://127.0.0.1:${proxy.address().port}`, NO_PROXY: '' } });
  let out = '';
  child.stdout.on('data', (d) => { out += d; });
  const code = await new Promise((r) => child.on('close', r));
  assert.equal(code, 0);
  assert.deepEqual(JSON.parse(out), { via: 'target' });
  assert.deepEqual(proxied, [targetHost]);
});
