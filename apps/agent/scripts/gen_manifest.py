"""Write dist/manifest.json: every built agent binary and its SHA-256.

The server reads this file to answer `GET /binary/{version}/{os}/{arch}`, to
embed the expected digest in the install script, and to decide which version an
update dispatch offers. It carries exactly one version — the one just built —
because the deployment artifact that contains it (the mono image, the native
bundle, the package) is replaced wholesale on upgrade, so accumulating older
entries here would describe binaries the artifact does not ship.

Failing loudly on an empty build is the point of the checks below. Writing
`{version: {}}` was worse than writing nothing: the key exists, so
`agent_update.latest_version()` returns it, and every install command and update
dispatch then 404s with "No binary for linux/amd64 at version X" on a
deployment whose build looked like it succeeded.
"""

import base64
import hashlib
import json
import os
import pathlib
import sys

if len(sys.argv) != 3:
    sys.exit(f"usage: {pathlib.Path(sys.argv[0]).name} <dist-dir> <version>")

dist = pathlib.Path(sys.argv[1])
version = sys.argv[2]

if not dist.is_dir():
    sys.exit(f"gen_manifest: {dist} is not a directory — nothing was built")

manifest = {version: {}}
# The `.sig` guard matters on a re-run: the glob would otherwise pick up
# signatures written by a previous pass and record digests for them as if
# they were binaries.
for f in sorted(dist.glob("cb-agent-*")):
    if not f.is_file() or f.suffix == ".sig":
        continue
    manifest[version][f.name.removeprefix("cb-agent-")] = hashlib.sha256(
        f.read_bytes()
    ).hexdigest()

# Slice 4.2 (F3): a detached Ed25519 signature over each binary. The digest
# above proves the download matches what the *server* said; only this proves
# the bytes came from whoever holds the signing key, which is what a
# compromised server cannot forge.
signing_key_b64 = os.environ.get("AGENT_SIGNING_PRIVATE_KEY", "")
if signing_key_b64:
    # Imported inside the branch so an unsigned build does not require
    # `cryptography` at all. A key that is present but unusable must fail
    # loudly rather than silently produce an unsigned release, so nothing
    # here is wrapped in a try.
    from cryptography.hazmat.primitives.asymmetric import ed25519

    private = ed25519.Ed25519PrivateKey.from_private_bytes(base64.b64decode(signing_key_b64))
    for f in sorted(dist.glob("cb-agent-*")):
        if not f.is_file() or f.suffix == ".sig":
            continue
        sig_path = f.with_name(f.name + ".sig")
        sig_path.write_bytes(base64.b64encode(private.sign(f.read_bytes())))
        manifest[version][f.name.removeprefix("cb-agent-") + ".sig"] = sig_path.name
else:
    # Warn loudly rather than failing. `make build-from-source` runs this
    # with no key and that path must keep working — a self-hoster has no
    # access to the release private key. Their agents run in warn mode.
    print(
        "gen_manifest: AGENT_SIGNING_PRIVATE_KEY not set — binaries are unsigned "
        "and agents will run in warn mode",
        file=sys.stderr,
    )

if not manifest[version]:
    sys.exit(
        f"gen_manifest: no cb-agent-* binaries in {dist}, so version {version} "
        f"would be published with nothing to download"
    )

(dist.parent / "manifest.json").write_text(json.dumps(manifest, indent=2))
