import hashlib
import json
import pathlib
import sys

dist = pathlib.Path(sys.argv[1])
version = sys.argv[2]

manifest = {version: {}}
for f in dist.glob("cb-agent-*"):
    arch_os = f.name.removeprefix("cb-agent-")
    manifest[version][arch_os] = hashlib.sha256(f.read_bytes()).hexdigest()

pathlib.Path("dist/manifest.json").write_text(json.dumps(manifest, indent=2))
