import { NATIVE_COMMANDS } from './inventory.js';

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

export function renderHelp(lookup) {
  const managed = NATIVE_COMMANDS.filter((c) => !c.lifecycle && c.name !== 'version');
  const width = Math.max(...[...managed.map((c) => c.name), ...OWN.map(([n]) => n)].map((n) => n.length)) + 2;
  const row = (name, summary) => `  ${name.padEnd(width)}${summary}\n`;
  let text = '\nCircuit Breaker CLI\n\nUsage: circuitbreaker <command> [options]\n\n';
  text += "Manage this install (runs the server's own cb):\n";
  for (const c of managed) text += row(c.name, c.summary);
  text += '\nThis CLI:\n';
  for (const [name, summary] of OWN) text += row(name, summary);
  text += '\nReview install/update --plan before --yes. Rollback can restore pre-update data with --restore-data. Downgrade and automated recover are deferred.\n';
  text += 'Machine output: --json prints one final JSON result on stdout; install/update/rollback --events=jsonl write JSONL events, and nothing else, on stderr. Native management and uninstall output are forwarded unchanged.\n\n';
  text += `Identity: ${lookup.status === 'found' ? lookup.path : lookup.status}\n`;
  if (lookup.status === 'found') text += `Mode:     ${lookup.identity.mode}\n`;
  return `${text}\n`;
}
