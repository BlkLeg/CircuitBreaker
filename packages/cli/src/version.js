import { EXIT } from './exit-codes.js';
import { loadIdentity } from './identity.js';
import { managementCompatibility } from './compat.js';

export function buildVersionReport(cliVersion, lookup) {
  const base = { schema_version: 1, cli_version: cliVersion, identity: lookup.status };
  if (lookup.status !== 'found') return { ...base, server: null, compatibility: null };
  const { version, mode, cli_path: cliPath = null } = lookup.identity;
  return {
    ...base,
    identity_path: lookup.path,
    server: { version, mode, cli_path: cliPath },
    compatibility: managementCompatibility(version, cliVersion),
  };
}

function renderVersion(report) {
  let text = `CLI       ${report.cli_version}\n`;
  if (!report.server) return `${text}Server    not found (identity ${report.identity})\n`;
  text += `Server    ${report.server.version} (${report.server.mode})\n`;
  text += `Identity  ${report.identity_path}\n`;
  text += `Managed   ${report.compatibility.certified ? 'yes' : 'no'}: ${report.compatibility.reason}\n`;
  return text;
}

export async function runVersion(args, deps) {
  const unknown = args.filter((a) => a !== '--json');
  if (unknown.length) {
    deps.err(`circuitbreaker version: unknown option '${unknown[0]}'\n`);
    return EXIT.USAGE;
  }
  const report = buildVersionReport(deps.cliVersion, await loadIdentity(deps));
  deps.out(args.includes('--json') ? `${JSON.stringify(report)}\n` : renderVersion(report));
  return EXIT.OK;
}
