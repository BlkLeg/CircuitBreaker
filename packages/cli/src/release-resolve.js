export const RELEASE_API = 'https://api.github.com/repos/BlkLeg/CircuitBreaker/releases';

export class UsageError extends Error { constructor(m) { super(m); this.code = 'USAGE'; } }
export class TargetError extends Error { constructor(m) { super(m); this.code = 'UNSUPPORTED'; } }

export function debArch(nodeArch) {
  return { x64: 'amd64', arm64: 'arm64' }[nodeArch] ?? null;
}

function pickAsset(release, name) {
  const found = release.assets?.find((a) => a.name === name);
  return found ? { id: found.id, name: found.name, size: found.size, url: found.browser_download_url } : null;
}

// Same selection rule as install.sh's cb_pick_release: newest non-draft, and for
// stable also non-prerelease. Resolved once; every later step uses the asset ids,
// sizes and URLs captured here, never a fresh `latest` lookup.
export async function resolveTarget({ version, channel, cliVersion, arch, fetchJson }) {
  if (version && channel) throw new UsageError('--version and --channel cannot be combined');
  if (channel && !['stable', 'candidate'].includes(channel)) throw new UsageError(`unknown channel '${channel}' (stable or candidate)`);
  if (!arch) throw new TargetError(`this CPU architecture is not supported (${process.arch}); Circuit Breaker ships amd64 and arm64`);

  let release;
  try {
    if (channel) {
      const list = await fetchJson(`${RELEASE_API}?per_page=30`);
      release = list.find((r) => !r.draft && (channel === 'candidate' || !r.prerelease));
    } else {
      const wanted = String(version ?? cliVersion).replace(/^v/, '');
      release = await fetchJson(`${RELEASE_API}/tags/v${wanted}`);
    }
  } catch (error) {
    if (error.code === 'HTTP_STATUS' && error.status === 404) release = undefined;
    else throw error;
  }
  if (!release) throw new TargetError(channel ? `no ${channel} release is published` : `release v${String(version ?? cliVersion).replace(/^v/, '')} not found`);

  const resolved = String(release.tag_name).replace(/^v/, '');
  const tarballName = `circuit-breaker_${resolved}_linux_${arch}.tar.gz`;
  const tarball = pickAsset(release, tarballName);
  if (!tarball) throw new TargetError(`release v${resolved} has no ${tarballName}`);
  return {
    version: resolved,
    tag: release.tag_name,
    explicitVersion: Boolean(version),
    channel: channel ?? null,
    arch,
    tarball,
    sums: pickAsset(release, 'SHA256SUMS'),
    sig: pickAsset(release, 'SHA256SUMS.sig'),
  };
}
