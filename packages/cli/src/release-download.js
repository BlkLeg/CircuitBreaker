import { open, readFile, writeFile, rename, rm, stat, statfs as fsStatfs } from 'node:fs/promises';
import { join, dirname } from 'node:path';
import { request, NetworkError } from './http.js';

export class DownloadError extends Error { constructor(m) { super(m); this.code = 'NETWORK'; } }
export class DiskSpaceError extends Error { constructor(m) { super(m); this.code = 'PREFLIGHT'; } }

const MARGIN = 64 * 1024 * 1024;
// A write the disk refuses for room is the disk-space preflight failing late
// (exit 7), never a network fault to retry.
const NO_ROOM = new Set(['ENOSPC', 'EDQUOT']);
const BACKOFF_MS = [1000, 2000, 4000];

async function sizeOf(path) {
  try { return (await stat(path)).size; } catch { return -1; }
}

async function identityMatches(sidecar, asset) {
  try {
    const recorded = JSON.parse(await readFile(sidecar, 'utf8'));
    return recorded.id === asset.id && recorded.size === asset.size && recorded.url === asset.url;
  } catch { return false; }
}

async function attempt(asset, part, start, { fetchImpl, timeoutMs }) {
  const headers = start > 0 ? { range: `bytes=${start}-` } : {};
  const controller = new AbortController();
  const response = await request(asset.url, { fetchImpl, timeoutMs, headers, signal: controller.signal });
  const appending = start > 0 && response.status === 206;
  if (appending) {
    const range = /^bytes (\d+)-(\d+)\/(\d+|\*)$/.exec(response.headers.get('content-range') ?? '');
    if (!range || Number(range[1]) !== start || (range[3] !== '*' && Number(range[3]) !== asset.size)) {
      await response.body?.cancel().catch(() => {});
      await rm(part, { force: true });
      throw new DownloadError(`${asset.name}: the server's partial answer does not continue the bytes already downloaded`);
    }
  }
  const handle = await open(part, appending ? 'a' : 'w', 0o600);
  let written = appending ? start : 0;
  // request() bounds connect + headers only, so the body gets a stall timeout:
  // timeoutMs without a chunk aborts the read (retryable; the .part is kept).
  let stall;
  let writeError;
  const arm = () => {
    clearTimeout(stall);
    stall = setTimeout(() => controller.abort(new DOMException('download stalled', 'TimeoutError')), timeoutMs);
  };
  try {
    arm();
    for await (const chunk of response.body) {
      arm();
      written += chunk.length;
      if (written > asset.size) throw new DownloadError(`${asset.name} is larger than the ${asset.size} bytes the release declares`);
      await handle.write(chunk).catch((error) => { writeError = error; throw error; });
    }
  } catch (error) {
    if (error instanceof DownloadError || error === writeError) throw error;
    throw new NetworkError(`download of ${asset.name} was interrupted`, error);
  } finally {
    clearTimeout(stall);
    await handle.close();
  }
  if (written !== asset.size) throw new DownloadError(`${asset.name} ended after ${written} of ${asset.size} bytes`);
}

function stagedPaths(asset, dir) {
  const final = join(dir, asset.name);
  return { final, part: `${final}.part`, sidecar: `${final}.asset.json` };
}

// Drops everything staged for one asset, so the next run downloads it again.
// Used when verification refuses what was downloaded: a file kept after a
// refusal would otherwise be reused, and refused, on every later run.
export async function discardAsset(asset, dir) {
  const { final, part, sidecar } = stagedPaths(asset, dir);
  for (const path of [final, part, sidecar]) await rm(path, { force: true });
}

export async function downloadAsset(asset, dir, options = {}) {
  try {
    return await stageAsset(asset, dir, options);
  } catch (error) {
    if (NO_ROOM.has(error?.code)) throw new DiskSpaceError(`no space left in ${dir} while staging ${asset.name} (${error.code})`);
    throw error;
  }
}

async function stageAsset(asset, dir, { fetchImpl = fetch, statfs = fsStatfs, sleep = (ms) => new Promise((r) => setTimeout(r, ms)), timeoutMs = 60000, retries = 3 }) {
  if (!Number.isSafeInteger(asset.size) || asset.size <= 0) throw new DownloadError(`${asset.name} declares an invalid size: ${asset.size}`);
  const { final, part, sidecar } = stagedPaths(asset, dir);
  const same = await identityMatches(sidecar, asset);
  if (same && await sizeOf(final) === asset.size) return final;
  if (!same) await rm(part, { force: true });
  await rm(final, { force: true });

  // Checked before the first byte is written, the identity record included.
  const space = await statfs(dirname(final));
  const have = await sizeOf(part);
  const need = asset.size - Math.max(have, 0) + MARGIN;
  if (space.bavail * space.bsize < need) {
    throw new DiskSpaceError(`not enough free space in ${dir} for ${asset.name} (${Math.ceil(need / 1048576)} MiB needed)`);
  }
  await writeFile(sidecar, JSON.stringify({ id: asset.id, size: asset.size, url: asset.url }), { mode: 0o600 });

  for (let tryNo = 0; ; tryNo += 1) {
    let start = await sizeOf(part);
    if (start < 0 || start >= asset.size) { await rm(part, { force: true }); start = 0; }
    try {
      await attempt(asset, part, start, { fetchImpl, timeoutMs });
      await rename(part, final);
      return final;
    } catch (error) {
      const retryable = error instanceof NetworkError || (error.code === 'HTTP_STATUS' && error.status >= 500) || error instanceof DownloadError;
      if (!retryable || tryNo >= retries) {
        if (error instanceof DownloadError) await rm(part, { force: true });
        throw error;
      }
      if (error instanceof DownloadError) await rm(part, { force: true });
      await sleep(BACKOFF_MS[Math.min(tryNo, BACKOFF_MS.length - 1)]);
    }
  }
}
