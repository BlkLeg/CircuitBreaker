// Build provenance: GitHub attestations for the bundle tarball, verified with
// sigstore against the release workflow on main. Required when online; the
// caller skips it in air-gap mode, where the signature alone decides.
export const ATTESTATION_API = 'https://api.github.com/repos/BlkLeg/CircuitBreaker/attestations';
export const ATTESTATION_ISSUER = 'https://token.actions.githubusercontent.com';
export const ATTESTATION_IDENTITY = 'https://github.com/BlkLeg/CircuitBreaker/.github/workflows/release.yml@refs/heads/main';

// Imported on first use, so commands that never verify provenance never load it.
export async function defaultSigstoreVerify(bundle, options) {
  const { verify } = await import('sigstore');
  await verify(bundle, options);
}

function statementOf(bundle) {
  try {
    return JSON.parse(Buffer.from(bundle.dsseEnvelope.payload, 'base64').toString('utf8'));
  } catch {
    return null;
  }
}

// { ok: true } once one bundle verifies for the pinned issuer and identity AND
// its in-toto subject names this sha256. 'none' means nothing was published for
// the digest; 'unverified' means something was, and none of it holds up. Other
// fetch failures propagate for the caller to report as network errors.
export async function verifyAttestation({ sha256, fetchJson, sigstoreVerify = defaultSigstoreVerify }) {
  let body;
  try {
    body = await fetchJson(`${ATTESTATION_API}/sha256:${sha256}`);
  } catch (error) {
    if (error.code === 'HTTP_STATUS' && error.status === 404) return { ok: false, reason: 'none' };
    throw error;
  }
  const bundles = (body?.attestations ?? []).map((a) => a?.bundle).filter(Boolean);
  if (bundles.length === 0) return { ok: false, reason: 'none' };
  for (const bundle of bundles) {
    try {
      await sigstoreVerify(bundle, { certificateIssuer: ATTESTATION_ISSUER, certificateIdentityURI: ATTESTATION_IDENTITY });
    } catch {
      continue;
    }
    // Read only after sigstore has verified the envelope that carries it.
    const statement = statementOf(bundle);
    if (Array.isArray(statement?.subject) && statement.subject.some((s) => s?.digest?.sha256 === sha256)) {
      return { ok: true };
    }
  }
  return { ok: false, reason: 'unverified' };
}
