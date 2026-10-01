import { createReadStream } from 'node:fs';
import { createGunzip } from 'node:zlib';
import { posix } from 'node:path';

export const ARCHIVE_LIMITS = Object.freeze({ maxEntries: 200_000, maxTotalBytes: 2 * 1024 ** 3 });

const FILE_TYPES = new Set(['0', '\0', '7']);
const SKIP_TYPES = new Set(['5']);

function field(buf, start, len) {
  const slice = buf.subarray(start, start + len);
  const end = slice.indexOf(0);
  return slice.subarray(0, end === -1 ? len : end).toString('utf8');
}

function number(buf, start, len) {
  if (buf[start] & 0x80) {
    let value = BigInt(buf[start] & 0x7f);
    for (let i = start + 1; i < start + len; i += 1) value = (value << 8n) | BigInt(buf[i]);
    return Number(value);
  }
  const text = field(buf, start, len).trim();
  return text ? parseInt(text, 8) : 0;
}

function checksumOk(header) {
  let sum = 0;
  for (let i = 0; i < 512; i += 1) sum += i >= 148 && i < 156 ? 32 : header[i];
  return sum === number(header, 148, 8);
}

// Relative, inside the archive root, after normalisation. Returns the problem or null.
function pathProblem(name) {
  if (name.startsWith('/')) return `absolute path ${name}`;
  const normal = posix.normalize(name.replace(/^\.\//, ''));
  if (normal === '..' || normal.startsWith('../')) return `${name} resolves outside the bundle`;
  return null;
}

function linkProblem(kind, name, target) {
  if (!target) return `${kind} ${name} has no target`;
  if (target.startsWith('/')) return `${kind} ${name} points at absolute ${target}`;
  const base = kind === 'symlink' ? posix.dirname(name.replace(/^\.\//, '')) : '.';
  const resolved = posix.normalize(posix.join(base, target));
  if (resolved === '..' || resolved.startsWith('../')) return `${kind} ${name} points outside the bundle (${target})`;
  return null;
}

function paxRecords(data) {
  const out = {};
  let text = data.toString('utf8');
  while (text.length) {
    const space = text.indexOf(' ');
    const length = Number(text.slice(0, space));
    if (!length) break;
    const record = text.slice(space + 1, length - 1);
    const eq = record.indexOf('=');
    out[record.slice(0, eq)] = record.slice(eq + 1);
    text = text.slice(length);
  }
  return out;
}

// Streams the gzip and walks ustar/GNU/pax headers without extracting anything.
export function checkArchive(path, limits = ARCHIVE_LIMITS) {
  return new Promise((resolve) => {
    let buffer = Buffer.alloc(0);
    let skip = 0;
    let collect = null; // { kind: 'L' | 'K' | 'x', remaining, chunks, pad }
    let pending = {};
    let entries = 0;
    let totalBytes = 0;
    let zeroBlocks = 0;
    let done = false;
    const input = createReadStream(path);
    const gunzip = createGunzip();
    const finish = (result) => {
      if (done) return;
      done = true;
      input.destroy();
      gunzip.destroy();
      resolve(result);
    };
    const fail = (reason) => finish({ ok: false, reason });

    gunzip.on('data', (chunk) => {
      buffer = Buffer.concat([buffer, chunk]);
      while (!done) {
        if (skip > 0) {
          const n = Math.min(skip, buffer.length);
          skip -= n;
          buffer = buffer.subarray(n);
          if (skip > 0) return;
          continue;
        }
        if (collect) {
          const n = Math.min(collect.remaining, buffer.length);
          collect.chunks.push(buffer.subarray(0, n));
          collect.remaining -= n;
          buffer = buffer.subarray(n);
          if (collect.remaining > 0) return;
          const data = Buffer.concat(collect.chunks);
          if (collect.kind === 'L') pending.path = field(data, 0, data.length);
          else if (collect.kind === 'K') pending.linkpath = field(data, 0, data.length);
          else Object.assign(pending, paxRecords(data));
          skip = collect.pad;
          collect = null;
          continue;
        }
        if (buffer.length < 512) return;
        const header = buffer.subarray(0, 512);
        buffer = buffer.subarray(512);
        if (header.every((b) => b === 0)) {
          zeroBlocks += 1;
          if (zeroBlocks >= 2) return finish({ ok: true, entries, totalBytes });
          continue;
        }
        zeroBlocks = 0;
        if (!checksumOk(header)) return fail('corrupt tar header (checksum mismatch)');
        const type = String.fromCharCode(header[156] || 48);
        const size = number(header, 124, 12);
        const pad = (512 - (size % 512)) % 512;
        if (type === 'L' || type === 'K' || type === 'x') {
          if (size > 1024 * 1024) return fail('oversized extended header');
          collect = { kind: type, remaining: size, chunks: [], pad };
          continue;
        }
        if (type === 'g') { skip = size + pad; continue; }
        const prefix = field(header, 345, 155);
        const name = pending.path ?? (prefix ? `${prefix}/${field(header, 0, 100)}` : field(header, 0, 100));
        const linkname = pending.linkpath ?? field(header, 157, 100);
        pending = {};
        entries += 1;
        if (entries > limits.maxEntries) return fail(`more than ${limits.maxEntries} entries`);
        const problem = pathProblem(name)
          ?? (type === '2' ? linkProblem('symlink', name, linkname) : null)
          ?? (type === '1' ? linkProblem('hardlink', name, linkname) : null)
          ?? (!FILE_TYPES.has(type) && !SKIP_TYPES.has(type) && type !== '1' && type !== '2' ? `unsupported entry type '${type}' for ${name}` : null);
        if (problem) return fail(problem);
        if (FILE_TYPES.has(type)) {
          totalBytes += size;
          if (totalBytes > limits.maxTotalBytes) return fail(`more than ${limits.maxTotalBytes} bytes of content`);
        }
        skip = FILE_TYPES.has(type) ? size + pad : pad;
      }
    });
    gunzip.on('end', () => fail('archive ended before the end-of-archive marker'));
    gunzip.on('error', (error) => fail(`not a valid gzip stream (${error.code ?? error.message})`));
    input.on('error', (error) => fail(`cannot read ${path} (${error.code})`));
    input.pipe(gunzip);
  });
}
