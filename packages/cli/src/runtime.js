// Checked by the launcher before anything else is imported, so an old Node or a
// wrong OS gets one sentence instead of a syntax error or stack trace.
export const MIN_NODE_MAJOR = 22;

export function unsupportedRuntime({ platform = process.platform, nodeVersion = process.versions.node } = {}) {
  if (platform !== 'linux') {
    return `Circuit Breaker's CLI supports Linux only; this host reports ${platform}.`;
  }
  const major = Number.parseInt(String(nodeVersion).split('.')[0], 10);
  if (!(major >= MIN_NODE_MAJOR)) {
    return `Node.js ${MIN_NODE_MAJOR} or newer is required; this is ${nodeVersion}.`;
  }
  return null;
}
