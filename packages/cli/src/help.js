import { NATIVE_COMMANDS } from './inventory.js';
import { CLI_VERSION } from './package-info.js';
import { redactText } from './lifecycle-contract.js';

const OWN = [
  ['install --plan', 'Resolve, download and verify a release; changes nothing [--json]'],
  ['install --yes', 'Install a verified release with native health checks'],
  ['update', 'Update native install [--plan | --check | --yes]'],
  ['rollback', 'Previous native update [--restore-data] [--yes]'],
  ['uninstall', 'Native removal; keeps data by default [--purge [--yes]]'],
  ['history', 'Lifecycle operations recorded on this host; read-only [--json]'],
  ['version', 'CLI and server versions, install mode, compatibility [--json]'],
  ['help', 'Show this help'],
];
const GROUPS = [
  ['OBSERVE', ['info', 'status', 'resources', 'logs', 'doctor', 'diag']],
  ['LIFECYCLE', ['install --plan', 'install --yes', 'update', 'rollback', 'history', 'restart', 'uninstall']],
  ['DATA & SETUP', ['backup', 'restore', 'setup', 'setup-token', 'config', 'migrate', 'vault-recover']],
  ['ACCESS & FLEET', ['token', 'user', 'agent']],
  ['CLI', ['version', 'help']],
];

export function renderHelp(lookup, { columns = 80, color = false } = {}) {
  const rows = new Map(NATIVE_COMMANDS.filter(c => !c.lifecycle).map(c => [c.name, c.summary]));
  for (const [name, summary] of OWN) rows.set(name, summary);
  const clean = v => redactText(String(v), { singleLine: true });
  const heading = s => color ? `\x1b[38;5;209m${s}\x1b[0m` : s;
  let text = `\nCircuit Breaker CLI\nCLI ${CLI_VERSION}`;
  if (lookup.status === 'found') text += ` · Server ${clean(lookup.identity.version)} · ${clean(lookup.identity.mode)}`;
  text += '\n\nUsage: circuitbreaker <command> [options]\n';
  for (const [group, commands] of GROUPS) {
    const available = commands.filter(c => rows.has(c));
    if (!available.length) continue;
    text += `\n${heading(group)}\n`;
    for (const name of available) text += columns >= 72 ? `  ${name.padEnd(19)}${rows.get(name)}\n` : `  ${name}\n    ${rows.get(name)}\n`;
  }
  text += '\nReview install/update --plan before --yes. Rollback can restore pre-update data with --restore-data.\n';
  text += 'Machine output: --json prints one final JSON result on stdout; install/update/rollback --events=jsonl write JSONL events, and nothing else, on stderr. Native management and uninstall output are forwarded unchanged.\n';
  text += 'Presentation: --no-animation disables lifecycle motion; NO_COLOR disables color.\n\n';
  text += `Identity: ${lookup.status === 'found' ? clean(lookup.path) : lookup.status}\n`;
  if (lookup.status === 'found') text += `Mode:     ${clean(lookup.identity.mode)}\n`;
  text += '\nTry: circuitbreaker resources --watch · circuitbreaker update --check\n';
  return `${text}\n`;
}
