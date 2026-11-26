import { parseArgs } from 'node:util';
import { EXIT } from './exit-codes.js';
import { confirmPhrase } from './rollback.js';
import { refuseWith } from './events.js';
import { loadIdentityFor } from './identity.js';
import { redactText } from './lifecycle-contract.js';

export function renderRemovalPlan(identity, purge) {
  const clean = text => redactText(String(text), { singleLine: true });
  let text = `\n${purge ? 'PURGE' : 'UNINSTALL'}  ${clean(identity?.mode ?? 'native command')} · ${clean(identity?.version ?? 'version unavailable')}\n\nPLAN BEFORE CHANGING ANYTHING\n`;
  if (identity?.mode === 'native' || identity?.mode === 'proxmox') {
    text += '  REMOVE  /opt/circuitbreaker and retained release trees\n  REMOVE  app services and app nginx site\n';
    text += `  ${purge ? 'DELETE' : 'KEEP'}    /etc/circuitbreaker — configuration, credentials and vault key\n`;
    text += `  ${purge ? 'DELETE' : 'KEEP'}    /var/lib/circuitbreaker — database, uploads and local backups\n`;
    text += `  ${purge ? 'DELETE' : 'KEEP'}    /var/backups/circuitbreaker — local backups\n  KEEP    shared nginx and system dependencies\n`;
  } else if (identity?.mode === 'package') {
    text += '  REMOVE  packaged app files and services\n';
    text += `  ${purge ? 'DELETE' : 'KEEP'}    /etc/circuit-breaker — configuration and vault key\n  ${purge ? 'DELETE' : 'KEEP'}    /var/lib/circuit-breaker — application data\n`;
  } else {
    text += `  REMOVE  application container ${clean(identity?.container_name ?? '(native uninstaller selects the installed container)')}\n`;
    text += `  ${purge ? 'DELETE' : 'KEEP'}    native uninstaller's selected data volume and configuration\n`;
  }
  text += '  KEEP    npm CLI (package removal is separate)\n';
  if (purge) text += '\nDeleting the vault key prevents decrypting retained data without an independent key copy.\nBackups inside deleted directories cannot recover this operation. External backups are not deleted.\n';
  text += '\nNo removal started by this command.\n';
  return text;
}

// The native uninstaller owns mode detection, its lock and the removal itself.
// The npm adapter adds only a purge acknowledgement and a keep-data default.
export async function runUninstall(args, deps, forward) {
  const refuse = (code, reason) => refuseWith(deps, { prefix: 'circuitbreaker uninstall', code, reason });
  try {
    const { values } = parseArgs({ args, strict: true, allowPositionals: false, options: { purge: { type: 'boolean' }, 'keep-data': { type: 'boolean' }, yes: { type: 'boolean' }, help: { type: 'boolean' } } });
    if (values.purge && values['keep-data']) return refuse(EXIT.USAGE, '--purge and --keep-data cannot be combined');
    if (values.help) { deps.out('usage: circuitbreaker uninstall [--keep-data | --purge [--yes]]\nDefault: retain data and the npm tool. Purge requires typing DELETE circuitbreaker or explicit --yes. Native uninstaller output and exit codes are preserved.\n'); return EXIT.OK; }
    const lookup = deps.env ? await loadIdentityFor(deps) : null;
    if (lookup && lookup.status !== 'found') return refuse(lookup.status === 'untrusted' ? EXIT.TRUST : EXIT.UNSUPPORTED, `install identity is ${lookup.status}; run cb doctor before removal`);
    deps.out(renderRemovalPlan(lookup?.identity, values.purge));
    if (values.purge && !values.yes && !await confirmPhrase('DELETE circuitbreaker', 'Purge permanently removes Circuit Breaker configuration and data using the native uninstaller.', deps)) return refuse(EXIT.USAGE, 'purge cancelled; nothing changed (unattended purge: --purge --yes)');
    const code = await forward('uninstall', [values.purge ? '--purge' : '--keep-data'], deps);
    if (code === EXIT.OK) deps.out(`\n${values.purge ? 'PURGE COMPLETE — native removal finished' : 'UNINSTALL COMPLETE — configuration and data retained'}\nThe npm CLI remains installed.\n`);
    return code;
  } catch (error) { return refuse(error.code?.startsWith('ERR_PARSE_ARGS') ? EXIT.USAGE : EXIT.UNSUPPORTED, error.message); }
}
