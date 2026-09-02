"""Generate an Ed25519 keypair for signing cb-agent update binaries.

For operators who build their own agent binaries (`make build-from-source`
cross-compiles them) and want their fleet to enforce signatures. The official
release keypair is generated the same way, but its private half lives only in
the release pipeline's secret store — never in this repository and never in
the application runtime.

Prints the public key for `make build-all SIGNING_PUBKEY=...` and writes the
private key to a file the caller must move somewhere safe.
"""

from __future__ import annotations

import base64
import os
import stat
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519


def main() -> int:
    """Write a fresh private key to argv[1] (default ./cb-agent-signing.key)
    and print its public half."""
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("cb-agent-signing.key")
    if out.exists():
        print(f"refusing to overwrite {out}", file=sys.stderr)
        return 1

    private = ed25519.Ed25519PrivateKey.generate()
    raw_private = private.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    raw_public = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    # 0600 before any bytes are written, via O_EXCL: a private key must never
    # exist on disk, even briefly, with a wider mode.
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "wb") as fh:
        fh.write(base64.b64encode(raw_private))

    print(f"private key written to {out} (mode 0600) — move it to your secret store")
    print("public key (pass to the agent build):")
    print(f"  SIGNING_PUBKEY={base64.b64encode(raw_public).decode()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
