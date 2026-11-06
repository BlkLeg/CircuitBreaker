export const RELEASE_API = 'https://api.github.com/repos/BlkLeg/CircuitBreaker/releases';

// A release version as --version names it and a tag carries it, v?X.Y.Z(-pre);
// never a path or a query, since it names API paths, staging and staged files.
export const VERSION_ARG = /^v?\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/;

export class UsageError extends Error { constructor(m) { super(m); this.code = 'USAGE'; } }
export class TargetError extends Error { constructor(m) { super(m); this.code = 'UNSUPPORTED'; } }
// An answer GitHub never gives (a non-version tag, another release than asked).
export class ReleaseAnswerError extends Error { constructor(m) { super(m); this.code = 'TRUST'; } }

export function debArch(nodeArch) {
  return { x64: 'amd64', arm64: 'arm64' }[nodeArch] ?? null;
}

function pickAsset(release, name) {
  const found = release.assets?.find((a) => a.name === name);
  return found ? { id: found.id, name: found.name, size: found.size, url: found.browser_download_url } : null;
}

// Answer text for a message: quoted, cut short, printable.
function shown(value) {
  return JSON.stringify(String(value).slice(0, 80)).replace(/[^\x20-\x7e]/g, '?');
}

// Same selection rule as install.sh's cb_pick_release: newest non-draft, and for
// stable also non-prerelease. Resolved once; every later step uses the asset ids,
// sizes and URLs captured here, never a fresh `latest` lookup.
export async function resolveTarget({ version, channel, cliVersion, arch, fetchJson }) {
  const explicit = version !== undefined && version !== null;
  if (explicit && channel) throw new UsageError('--version and --channel cannot be combined');
  if (channel && !['stable', 'candidate'].includes(channel)) throw new UsageError(`unknown channel '${channel}' (stable or candidate)`);
  if (explicit && !VERSION_ARG.test(String(version))) {
    throw new UsageError(`--version '${version}' is not a release version (for example 0.4.7)`);
  }
  if (!arch) throw new TargetError(`this CPU architecture is not supported (${process.arch}); Circuit Breaker ships amd64 and arm64`);

  const wanted = String(explicit ? version : cliVersion).replace(/^v/, '');
  let release;
  try {
    if (channel) {
      const list = await fetchJson(`${RELEASE_API}?per_page=30`);
      release = list.find((r) => !r.draft && (channel === 'candidate' || !r.prerelease));
    } else {
      release = await fetchJson(`${RELEASE_API}/tags/v${wanted}`);
    }
  } catch (error) {
    if (error.code === 'HTTP_STATUS' && error.status === 404) release = undefined;
    else throw error;
  }
  if (!release) throw new TargetError(channel ? `no ${channel} release is published` : `release v${wanted} not found`);

  // The tag names staging paths, and GitHub answers tags/vX with vX: any other
  // answer did not come from it unchanged. Refused before anything is staged.
  const tag = release.tag_name;
  if (typeof tag !== 'string' || !VERSION_ARG.test(tag)) {
    throw new ReleaseAnswerError(`GitHub's answer names release tag ${shown(tag)}, which is not a release version; refusing it`);
  }
  const resolved = tag.replace(/^v/, '');
  if (!channel && resolved !== wanted) {
    throw new ReleaseAnswerError(`asked for release v${wanted} but GitHub answered with ${tag} — the release answer may have been tampered with`);
  }
  const tarballName = `circuit-breaker_${resolved}_linux_${arch}.tar.gz`;
  const tarball = pickAsset(release, tarballName);
  if (!tarball) throw new TargetError(`release v${resolved} has no ${tarballName}`);
  return {
    version: resolved,
    tag,
    explicitVersion: explicit,
    // What --version asked for, or null: only this may exempt an older release from signing.
    requestedVersion: explicit ? wanted : null,
    channel: channel ?? null,
    arch,
    tarball,
    sums: pickAsset(release, 'SHA256SUMS'),
    sig: pickAsset(release, 'SHA256SUMS.sig'),
  };
}
