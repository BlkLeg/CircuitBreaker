import { open, readFile, writeFile, rename, rm, stat, statfs as fsStatfs } from 'node:fs/promises';
import { join, dirname } from 'node:path';
import { request, NetworkError } from './http.js';

export class DownloadError extends Error { constructor(m) { super(m); this.code = 'NETWORK'; } }
export class DiskSpaceError extends Error { constructor(m) { super(m); this.code = 'PREFLIGHT'; } }

const MARGIN = 64 * 1024 * 1024;
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
  const handle = await open(part, appending ? 'a' : 'w', 0o600);
  let written = appending ? start : 0;
  // request() bounds connect + headers only, so the body gets a stall timeout:
  // timeoutMs without a chunk aborts the read (retryable; the .part is kept).
  let stall;
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
      await handle.write(chunk);
    }
  } catch (error) {
    if (error instanceof DownloadError) throw error;
    throw new NetworkError(`download of ${asset.name} was interrupted`, error);
  } finally {
    clearTimeout(stall);
    await handle.close();
  }
  if (written !== asset.size) throw new DownloadError(`${asset.name} ended after ${written} of ${asset.size} bytes`);
}

export async function downloadAsset(asset, dir, { fetchImpl = fetch, statfs = fsStatfs, sleep = (ms) => new Promise((r) => setTimeout(r, ms)), timeoutMs = 60000, retries = 3 } = {}) {
  if (!Number.isSafeInteger(asset.size) || asset.size <= 0) throw new DownloadError(`${asset.name} declares an invalid size: ${asset.size}`);
  const final = join(dir, asset.name);
  const part = `${final}.part`;
  const sidecar = `${final}.asset.json`;
  const same = await identityMatches(sidecar, asset);
  if (same && await sizeOf(final) === asset.size) return final;
  if (!same) await rm(part, { force: true });
  await rm(final, { force: true });
  await writeFile(sidecar, JSON.stringify({ id: asset.id, size: asset.size, url: asset.url }), { mode: 0o600 });

  const space = await statfs(dirname(final));
  const have = await sizeOf(part);
  const need = asset.size - Math.max(have, 0) + MARGIN;
  if (space.bavail * space.bsize < need) {
    throw new DiskSpaceError(`not enough free space in ${dir} for ${asset.name} (${Math.ceil(need / 1048576)} MiB needed)`);
  }

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
