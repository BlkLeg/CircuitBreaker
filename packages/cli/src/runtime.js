// Checked by the launcher before anything else is imported, so an old Node or a
// wrong OS gets one sentence instead of a syntax error or stack trace.
//
// The floor is sigstore 5's engines range, the one runtime dependency's: below it
// provenance verification cannot load. package.json's engines states the same
// string, and a test keeps the two equal.
export const NODE_ENGINES = '^22.22.2 || ^24.15.0 || >=26.0.0';

// [major, lowest accepted minor.patch within it]; majors from OPEN_FROM up are all accepted.
const PINNED_LINES = new Map([[22, [22, 2]], [24, [15, 0]]]);
const OPEN_FROM = 26;

function supportedNode(nodeVersion) {
  const match = /^(\d+)\.(\d+)\.(\d+)/.exec(String(nodeVersion));
  if (!match) return false;
  const [major, minor, patch] = match.slice(1).map(Number);
  if (major >= OPEN_FROM) return true;
  const floor = PINNED_LINES.get(major);
  if (!floor) return false;
  return minor > floor[0] || (minor === floor[0] && patch >= floor[1]);
}

export function unsupportedRuntime({ platform = process.platform, nodeVersion = process.versions.node } = {}) {
  if (platform !== 'linux') {
    return `Circuit Breaker's CLI supports Linux only; this host reports ${platform}.`;
  }
  if (!supportedNode(nodeVersion)) {
    return `Node.js 22.22.2+, 24.15.0+ or 26+ is required; this is ${nodeVersion}.`;
  }
  return null;
}
