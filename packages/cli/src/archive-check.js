import { createReadStream } from 'node:fs';
import { createGunzip } from 'node:zlib';

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

// Splits an entry name into segments. Dot segments and empty segments are dropped;
// a leading '/' or any '..' segment is refused outright (the extractor writes
// through symlinks, so a '..' can never be proven to stay inside the bundle).
function splitName(name) {
  if (name.startsWith('/')) return { problem: `absolute path ${name}` };
  const segments = name.split('/').filter((s) => s !== '' && s !== '.');
  if (segments.includes('..')) return { problem: `${name} has a '..' segment and may resolve outside the bundle` };
  return { segments };
}

// Walks a link target component by component. `symlinks` holds every symlink
// entry path seen in the archive. Returns the problem or null.
function linkProblem(kind, name, segments, target, symlinks) {
  if (!target) return `${kind} ${name} has no target`;
  if (target.startsWith('/')) return `${kind} ${name} points at absolute ${target}`;
  const parts = target.split('/').filter((s) => s !== '' && s !== '.');
  const stack = kind === 'symlink' ? segments.slice(0, -1) : [];
  for (let i = 0; i < parts.length; i += 1) {
    if (parts[i] === '..') {
      if (stack.length === 0) return `${kind} ${name} points outside the bundle (${target})`;
      stack.pop();
    } else {
      stack.push(parts[i]);
    }
    if (i < parts.length - 1 && symlinks.has(stack.join('/'))) {
      return `${kind} ${name} points through symlink ${stack.join('/')} (${target})`;
    }
  }
  if (kind === 'hardlink' && symlinks.has(stack.join('/'))) {
    return `${kind} ${name} targets symlink ${stack.join('/')}`;
  }
  return null;
}

// Pax records are "<length> <key>=<value>\n" where length counts bytes of the
// whole record. Returns null when any record is malformed.
function paxRecords(data) {
  const out = {};
  let offset = 0;
  while (offset < data.length) {
    const space = data.indexOf(0x20, offset);
    if (space === -1) return null;
    const lengthText = data.subarray(offset, space).toString('latin1');
    if (!/^[0-9]+$/.test(lengthText)) return null;
    const length = Number(lengthText);
    const end = offset + length;
    if (length <= space - offset + 1 || end > data.length || data[end - 1] !== 0x0a) return null;
    const record = data.subarray(space + 1, end - 1).toString('utf8');
    const eq = record.indexOf('=');
    if (eq < 1) return null;
    out[record.slice(0, eq)] = record.slice(eq + 1);
    offset = end;
  }
  return out;
}

// Streams the gzip and walks ustar/GNU/pax headers without extracting anything.
export function checkArchive(path, limits = ARCHIVE_LIMITS) {
  return new Promise((resolve) => {
    let buffer = Buffer.alloc(0);
    let skip = 0;
    let collect = null; // { kind: 'L' | 'K' | 'x' | 'g', remaining, chunks, pad }
    let pending = {};
    let entries = 0;
    let totalBytes = 0;
    let zeroBlocks = 0;
    const symlinks = new Set();
    const seen = []; // { name, segments } for every entry
    const links = []; // { kind, name, segments, target }
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
    // Needs the whole entry set, so entry order cannot matter.
    const crossCheck = () => {
      for (const { name, segments } of seen) {
        for (let i = 1; i < segments.length; i += 1) {
          const prefix = segments.slice(0, i).join('/');
          if (symlinks.has(prefix)) return `${name} is written through symlink ${prefix}`;
        }
      }
      for (const { kind, name, segments, target } of links) {
        const problem = linkProblem(kind, name, segments, target, symlinks);
        if (problem) return problem;
      }
      return null;
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
          else {
            const records = paxRecords(data);
            if (!records) return fail('malformed pax extended header');
            if (Object.keys(records).some((key) => key.startsWith('GNU.sparse.'))) {
              return fail('GNU sparse headers are not supported');
            }
            if (collect.kind === 'x') {
              for (const key of ['path', 'linkpath', 'size']) if (key in records) pending[key] = records[key];
            }
          }
          skip = collect.pad;
          collect = null;
          continue;
        }
        if (buffer.length < 512) return;
        const header = buffer.subarray(0, 512);
        buffer = buffer.subarray(512);
        if (header.every((b) => b === 0)) {
          zeroBlocks += 1;
          if (zeroBlocks >= 2) {
            const problem = crossCheck();
            return problem ? fail(problem) : finish({ ok: true, entries, totalBytes });
          }
          continue;
        }
        zeroBlocks = 0;
        if (!checksumOk(header)) return fail('corrupt tar header (checksum mismatch)');
        const type = String.fromCharCode(header[156] || 48);
        let size = number(header, 124, 12);
        const pad = (512 - (size % 512)) % 512;
        if (type === 'L' || type === 'K' || type === 'x' || type === 'g') {
          if (size > 1024 * 1024) return fail('oversized extended header');
          collect = { kind: type, remaining: size, chunks: [], pad };
          continue;
        }
        if (pending.size !== undefined && !FILE_TYPES.has(type)) {
          return fail(`pax size on non-file entry type '${type}' is not supported`);
        }
        if (pending.size !== undefined) {
          if (!/^[0-9]+$/.test(pending.size)) return fail('malformed pax size');
          size = Number(pending.size);
        }
        const prefix = field(header, 345, 155);
        const name = pending.path ?? (prefix ? `${prefix}/${field(header, 0, 100)}` : field(header, 0, 100));
        const linkname = pending.linkpath ?? field(header, 157, 100);
        pending = {};
        entries += 1;
        if (entries > limits.maxEntries) return fail(`more than ${limits.maxEntries} entries`);
        const split = splitName(name);
        let problem = split.problem ?? null;
        if (!problem && !FILE_TYPES.has(type) && !SKIP_TYPES.has(type) && type !== '1' && type !== '2') {
          problem = `unsupported entry type '${type}' for ${name}`;
        }
        if (problem) return fail(problem);
        const segments = split.segments;
        const joined = segments.join('/');
        seen.push({ name, segments });
        if (type === '2') symlinks.add(joined);
        if (type === '1' || type === '2') {
          links.push({ kind: type === '2' ? 'symlink' : 'hardlink', name, segments, target: linkname });
        }
        const entryPad = (512 - (size % 512)) % 512;
        if (FILE_TYPES.has(type)) {
          totalBytes += size;
          if (totalBytes > limits.maxTotalBytes) return fail(`more than ${limits.maxTotalBytes} bytes of content`);
        }
        skip = FILE_TYPES.has(type) ? size + entryPad : 0;
      }
    });
    gunzip.on('end', () => fail('archive ended before the end-of-archive marker'));
    gunzip.on('error', (error) => fail(`not a valid gzip stream (${error.code ?? error.message})`));
    input.on('error', (error) => fail(`cannot read ${path} (${error.code})`));
    input.pipe(gunzip);
  });
}
