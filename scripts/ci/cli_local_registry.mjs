// A one-package npm registry on 127.0.0.1 for the packed-CLI smoke.
//
// Usage: node cli_local_registry.mjs <package.tgz> <package.json>
// Prints the port it listens on, then serves until killed:
//   GET /<name>     the packument, one version, with `_hasShrinkwrap: true`
//                   when the tarball ships npm-shrinkwrap.json (npmjs.com sets
//                   that flag on publish, and npm honours the shrinkwrap only
//                   when it is set; a plain `npm install <file.tgz>` ignores it)
//   GET /pkg.tgz    the tarball
// Everything else is 404, so the smoke points only the package's scope here.
import { createServer } from 'node:http';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { gunzipSync } from 'node:zlib';

const [tgzPath, manifestPath] = process.argv.slice(2);
if (!tgzPath || !manifestPath) {
  console.error('usage: cli_local_registry.mjs <package.tgz> <package.json>');
  process.exit(2);
}
const tarball = readFileSync(tgzPath);
const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));

// True when the tar holds package/npm-shrinkwrap.json (ustar names are the
// first 100 bytes of each 512-byte header).
function shipsShrinkwrap(gz) {
  const tar = gunzipSync(gz);
  for (let at = 0; at + 512 <= tar.length;) {
    const name = tar.subarray(at, at + 100).toString('utf8').replace(/\0.*$/s, '');
    if (!name) return false;
    if (name === 'package/npm-shrinkwrap.json') return true;
    const size = parseInt(tar.subarray(at + 124, at + 136).toString('utf8').replace(/\0.*$/s, '').trim() || '0', 8);
    at += 512 + Math.ceil(size / 512) * 512;
  }
  return false;
}

const integrity = `sha512-${createHash('sha512').update(tarball).digest('base64')}`;
const hasShrinkwrap = shipsShrinkwrap(tarball);
const server = createServer((req, res) => {
  const base = `http://127.0.0.1:${server.address().port}`;
  if (req.url === '/pkg.tgz') {
    res.writeHead(200, { 'content-type': 'application/octet-stream' });
    res.end(tarball);
    return;
  }
  if (decodeURIComponent(req.url).toLowerCase() === `/${manifest.name}`) {
    const version = { ...manifest, _hasShrinkwrap: hasShrinkwrap, dist: { tarball: `${base}/pkg.tgz`, integrity } };
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ name: manifest.name, 'dist-tags': { latest: manifest.version }, versions: { [manifest.version]: version } }));
    return;
  }
  res.writeHead(404, { 'content-type': 'application/json' });
  res.end('{"error":"not found"}');
});
server.listen(0, '127.0.0.1', () => console.log(server.address().port));
