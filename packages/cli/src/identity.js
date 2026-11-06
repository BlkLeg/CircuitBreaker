import { readFile as fsReadFile } from 'node:fs/promises';
import { readFileSync } from 'node:fs';
import { checkTrustedFile } from './trust.js';

// A byte copy of specs/install/identity.schema.json; tests/build/test_cli_package.py
// fails if the two diverge.
const SCHEMA = JSON.parse(
  readFileSync(new URL('../schemas/install-identity.schema.json', import.meta.url), 'utf8'),
);

// Mirrors cb_identity_candidate_paths in deploy/lib/install-identity.sh, minus the
// explicit CB_IDENTITY_PATH, which loadIdentity treats as exclusive, as cb does.
export function candidatePaths({ env, home }) {
  const paths = ['/etc/circuitbreaker/install-identity.json', '/etc/circuit-breaker/install-identity.json'];
  if (env.CB_DATA_DIR) paths.push(`${env.CB_DATA_DIR.replace(/\/$/, '')}/install-identity.json`);
  if (home) paths.push(`${home}/.circuit-breaker/install-identity.json`);
  return paths;
}

function checkValue(key, value, rule) {
  if (rule.type === 'integer' && !Number.isInteger(value)) return [`'${key}' must be an integer`];
  if (rule.type === 'string' && typeof value !== 'string') return [`'${key}' must be a string`];
  if (rule.type === 'array') {
    if (!Array.isArray(value)) return [`'${key}' must be an array`];
    return value.flatMap((item, i) => checkValue(`${key}[${i}]`, item, rule.items));
  }
  const problems = [];
  if ('const' in rule && value !== rule.const) problems.push(`'${key}' must be ${JSON.stringify(rule.const)}`);
  if (rule.enum && !rule.enum.includes(value)) problems.push(`'${key}' must be one of ${rule.enum.join(', ')}`);
  if (rule.minLength !== undefined && value.length < rule.minLength) problems.push(`'${key}' must not be empty`);
  return problems;
}

// Validates against the schema's own rules. It supports only the keywords that schema
// uses, and a test fails if it starts using another.
export function validateIdentity(doc) {
  if (doc === null || typeof doc !== 'object' || Array.isArray(doc)) return ['identity is not a JSON object'];
  const problems = SCHEMA.required.filter((key) => !(key in doc)).map((key) => `missing required field '${key}'`);
  for (const [key, value] of Object.entries(doc)) {
    const rule = Object.hasOwn(SCHEMA.properties, key) ? SCHEMA.properties[key] : null;
    if (!rule) problems.push(`unknown field '${key}'`);
    else problems.push(...checkValue(key, value, rule));
  }
  return problems;
}

const ABSENT = new Set(['ENOENT', 'ENOTDIR', 'EISDIR']);
const DENIED = new Set(['EACCES', 'EPERM']);

export async function loadIdentity({ env, home, readFile = fsReadFile }) {
  const searched = env.CB_IDENTITY_PATH ? [env.CB_IDENTITY_PATH] : candidatePaths({ env, home });
  let unreadable = null;
  for (const path of searched) {
    let text;
    try {
      text = await readFile(path, 'utf8');
    } catch (error) {
      if (DENIED.has(error.code)) {
        unreadable ??= path;
        continue;
      }
      if (ABSENT.has(error.code)) continue;
      throw error;
    }
    let doc;
    try {
      doc = JSON.parse(text);
    } catch {
      return { status: 'invalid', path, problems: ['not valid JSON'] };
    }
    const problems = validateIdentity(doc);
    return problems.length ? { status: 'invalid', path, problems } : { status: 'found', path, identity: doc };
  }
  return unreadable ? { status: 'unreadable', path: unreadable, searched } : { status: 'missing', searched };
}

// Under root an identity file is trusted before it is read, and the bytes come from the
// resolved path that was judged, so a path component swapped between check and read
// cannot make root believe a file an unprivileged user wrote. A refusal surfaces as
// status 'untrusted'; non-root lookups are plain loadIdentity.
export async function loadIdentityFor(deps) {
  if (deps.euid !== 0) return loadIdentity(deps);
  const readFile = async (candidate, encoding) => {
    const trusted = await checkTrustedFile(candidate, { stat: deps.stat, realpath: deps.realpath, trustedUids: [0] });
    if (!trusted.ok) {
      if (trusted.code === 'ENOENT' || trusted.code === 'ENOTDIR') {
        throw Object.assign(new Error(trusted.reason), { code: trusted.code });
      }
      throw Object.assign(new Error(trusted.reason), { code: 'EUNTRUSTED', path: candidate });
    }
    return deps.readFile(trusted.path, encoding);
  };
  try {
    return await loadIdentity({ ...deps, readFile });
  } catch (error) {
    if (error.code === 'EUNTRUSTED') return { status: 'untrusted', path: error.path, reason: error.message };
    throw error;
  }
}
