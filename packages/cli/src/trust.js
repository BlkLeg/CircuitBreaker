import { stat as fsStat, realpath as fsRealpath } from 'node:fs/promises';
import { dirname, isAbsolute } from 'node:path';

const GROUP_OR_OTHER_WRITE = 0o022;

// Decides whether a file may be executed or believed. It resolves symlinks first,
// then judges the real file and the directory that holds it. The returned path is
// the resolved one, so a link swapped after this check cannot redirect execution.
export async function checkTrustedFile(
  path,
  { stat = fsStat, realpath = fsRealpath, trustedUids = [0], executable = false } = {},
) {
  if (!isAbsolute(path)) return { ok: false, reason: `${path} is not an absolute path` };
  let real;
  try {
    real = await realpath(path);
  } catch (error) {
    return { ok: false, reason: `${path} cannot be resolved (${error.code})`, code: error.code };
  }
  let file;
  try {
    file = await stat(real);
  } catch (error) {
    return { ok: false, reason: `${real} cannot be inspected (${error.code})`, code: error.code };
  }
  if (!file.isFile()) return { ok: false, reason: `${real} is not a regular file` };
  if (executable && (file.mode & 0o111) === 0) return { ok: false, reason: `${real} is not executable` };
  const parent = dirname(real);
  let parentInfo;
  try {
    parentInfo = await stat(parent);
  } catch (error) {
    return { ok: false, reason: `${parent} cannot be inspected (${error.code})`, code: error.code };
  }
  for (const [label, target, info] of [['file', real, file], ['directory', parent, parentInfo]]) {
    if (!trustedUids.includes(info.uid)) {
      return { ok: false, reason: `${label} ${target} is owned by uid ${info.uid}, not ${trustedUids.join(' or ')}` };
    }
    if ((info.mode & GROUP_OR_OTHER_WRITE) !== 0) {
      return { ok: false, reason: `${label} ${target} is writable by group or others` };
    }
  }
  return { ok: true, path: real };
}
