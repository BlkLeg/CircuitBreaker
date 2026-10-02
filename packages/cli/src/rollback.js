import { parseArgs } from 'node:util';
import { createInterface } from 'node:readline/promises';
import { trustedIdentity, executeScript } from './lifecycle.js';
import { checkTrustedFile } from './trust.js';
import { refuseWith } from './events.js';
import { EXIT } from './exit-codes.js';

export async function confirmPhrase(phrase, message, deps) {
  if (deps.confirm) return deps.confirm(phrase, message);
  if (!process.stdin.isTTY) return false;
  const prompt = createInterface({ input: process.stdin, output: process.stderr });
  try { return await prompt.question(`${message}\nType ${phrase} to proceed: `) === phrase; }
  finally { prompt.close(); }
}

export async function runRollback(args, deps) {
  const json = args.includes('--json');
  const refuse = (code, reason) => refuseWith(deps, { prefix: 'circuitbreaker rollback', code, reason, result: json ? { schema_version: 1, action: 'rollback', operation_id: null, current_version: null, target_version: null, recovery_available: false } : null });
  try {
    const { values } = parseArgs({ args, strict: true, allowPositionals: false, options: { yes: { type: 'boolean' }, 'restore-data': { type: 'boolean' }, json: { type: 'boolean' }, events: { type: 'string' } } });
    const identity = await trustedIdentity(deps);
    if (identity.mode !== 'native') return refuse(EXIT.UNSUPPORTED, 'rollback supports native installs with a retained previous update');
    if (!values.yes && !await confirmPhrase(values['restore-data'] ? 'RESTORE' : 'ROLLBACK', values['restore-data'] ? 'Rollback replaces the database, uploads and vault key with the pre-update snapshot.' : 'Rollback replaces the release and retains current data. A safety snapshot is taken first.', deps)) return refuse(EXIT.USAGE, 'rollback cancelled; nothing changed (unattended: --yes; data replacement additionally requires --restore-data)');
    const trusted = await checkTrustedFile('/opt/circuitbreaker/deploy/scripts/rollback-release.sh', deps);
    if (!trusted.ok) return refuse(EXIT.TRUST, `cannot run rollback: ${trusted.reason}`);
    deps.events?.phase('recover', 'started');
    const stopped = await executeScript(trusted.path, ['--npm-result', ...(values['restore-data'] ? ['--restore-data'] : [])], { ...deps, captureResult: true }, json);
    deps.events?.phase('recover', stopped.code === 0 ? 'completed' : 'failed');
    if (!stopped.result) return refuse(stopped.code || EXIT.MANUAL, 'rollback returned no final result; run cb doctor and inspect retained releases');
    if (stopped.result.action !== 'rollback') return refuse(EXIT.MANUAL, 'unexpected native rollback result; inspect history');
    if (json) deps.result.write(stopped.result);
    return stopped.result.outcome === 'committed' ? EXIT.OK : stopped.code || EXIT.MANUAL;
  } catch (error) { return refuse(typeof error.code === 'number' ? error.code : error.code?.startsWith('ERR_PARSE_ARGS') ? EXIT.USAGE : EXIT.MANUAL, error.message); }
}
