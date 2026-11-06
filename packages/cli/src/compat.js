import { readFileSync } from 'node:fs';

const table = JSON.parse(readFileSync(new URL('../compat/management.json', import.meta.url), 'utf8'));

// Whether this CLI may manage a server of the given version. The server's own
// release is always certified, because both come from the same tree. Older releases
// are certified only when listed, never by comparing version numbers.
export function managementCompatibility(serverVersion, cliVersion) {
  if (serverVersion === cliVersion) {
    return { certified: true, reason: 'same release as this CLI' };
  }
  if (table.certified_servers.includes(serverVersion)) {
    return { certified: true, reason: 'certified for management by this CLI' };
  }
  return {
    certified: false,
    reason: `server ${serverVersion} is not in this CLI's management table (certified: ${cliVersion}, ${table.certified_servers.join(', ')})`,
  };
}
