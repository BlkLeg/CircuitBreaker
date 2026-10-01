import { mkdir, stat, chmod } from 'node:fs/promises';
import { join } from 'node:path';

export class StagingError extends Error { constructor(m) { super(m); this.code = 'PREFLIGHT'; } }

// Per-user cache, keyed by the immutable target, private to the user. Staging
// only: nothing here is trusted until verification passes, and installation
// (sub-plan 05) copies accepted bytes to root-controlled storage.
export async function stagingDir({ env, home, version, arch, uid }) {
  const base = env.XDG_CACHE_HOME || join(home, '.cache');
  const dir = join(base, 'circuitbreaker', 'staging', `${version}-${arch}`);
  await mkdir(dir, { recursive: true, mode: 0o700 });
  const info = await stat(dir);
  if (info.uid !== uid) throw new StagingError(`${dir} is owned by uid ${info.uid}, not you; remove it and retry`);
  if ((info.mode & 0o077) !== 0) {
    throw new StagingError(`${dir} is accessible to other users (mode ${(info.mode & 0o777).toString(8)}); run: chmod 700 ${dir}`);
  }
  await chmod(dir, 0o700);
  return dir;
}
