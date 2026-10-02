import { parseArgs } from 'node:util';
import { EXIT } from './exit-codes.js';
import { confirmPhrase } from './rollback.js';
import { refuseWith } from './events.js';

// The native uninstaller owns mode detection, its lock and the removal itself.
// The npm adapter adds only a purge acknowledgement and a keep-data default.
export async function runUninstall(args, deps, forward) {
  const refuse = (code, reason) => refuseWith(deps, { prefix: 'circuitbreaker uninstall', code, reason });
  try {
    const { values } = parseArgs({ args, strict: true, allowPositionals: false, options: { purge: { type: 'boolean' }, 'keep-data': { type: 'boolean' }, yes: { type: 'boolean' }, help: { type: 'boolean' } } });
    if (values.purge && values['keep-data']) return refuse(EXIT.USAGE, '--purge and --keep-data cannot be combined');
    if (values.help) { deps.out('usage: circuitbreaker uninstall [--keep-data | --purge [--yes]]\nDefault: retain data and the npm tool. Purge requires typing DELETE or explicit --yes. Native uninstaller output and exit codes are preserved.\n'); return EXIT.OK; }
    if (values.purge && !values.yes && !await confirmPhrase('DELETE', 'Purge permanently removes Circuit Breaker configuration and data using the native uninstaller.', deps)) return refuse(EXIT.USAGE, 'purge cancelled; nothing changed (unattended purge: --purge --yes)');
    return forward('uninstall', [values.purge ? '--purge' : '--keep-data'], deps);
  } catch (error) { return refuse(error.code?.startsWith('ERR_PARSE_ARGS') ? EXIT.USAGE : EXIT.UNSUPPORTED, error.message); }
}
