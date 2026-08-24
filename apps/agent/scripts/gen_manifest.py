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

import hashlib
import json
import pathlib
import sys

if len(sys.argv) != 3:
    sys.exit(f"usage: {pathlib.Path(sys.argv[0]).name} <dist-dir> <version>")

dist = pathlib.Path(sys.argv[1])
version = sys.argv[2]

if not dist.is_dir():
    sys.exit(f"gen_manifest: {dist} is not a directory — nothing was built")

manifest = {version: {}}
for f in sorted(dist.glob("cb-agent-*")):
    if not f.is_file():
        continue
    manifest[version][f.name.removeprefix("cb-agent-")] = hashlib.sha256(
        f.read_bytes()
    ).hexdigest()

if not manifest[version]:
    sys.exit(
        f"gen_manifest: no cb-agent-* binaries in {dist}, so version {version} "
        f"would be published with nothing to download"
    )

(dist.parent / "manifest.json").write_text(json.dumps(manifest, indent=2))
