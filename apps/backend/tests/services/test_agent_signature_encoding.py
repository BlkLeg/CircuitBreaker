"""Slice 4.2 (F3): the release signer and the agent verifier must agree.

The two halves of this mechanism are in different languages and were written
independently — `apps/agent/scripts/gen_manifest.py` produces the signature,
`apps/agent/internal/update/signature.go` checks it. Nothing in either
suite alone would catch an encoding mismatch: the Go tests sign their own
fixtures, and the Python side has no verifier. This pins the wire contract
they share, which is where a silent break would live.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

GEN_MANIFEST = Path(__file__).resolve().parents[3] / "agent" / "scripts" / "gen_manifest.py"


@pytest.fixture
def signed_build(tmp_path):
    """Run the real release signer over a fake binary and hand back its
    output plus the public half of the key that signed it."""
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

    dist = tmp_path / "1.0.0"
    dist.mkdir()
    binary = dist / "cb-agent-linux-amd64"
    binary.write_bytes(b"fake agent binary contents")

    subprocess.run(
        [sys.executable, str(GEN_MANIFEST), str(dist), "1.0.0"],
        check=True,
        env={**os.environ, "AGENT_SIGNING_PRIVATE_KEY": base64.b64encode(raw_private).decode()},
        capture_output=True,
    )
    return binary, dist / "cb-agent-linux-amd64.sig", raw_public, tmp_path


def test_the_signature_is_base64_of_a_raw_64_byte_signature(signed_build):
    """The exact encoding `VerifySignature` decodes: base64 of the raw
    Ed25519 signature, nothing wrapped around it."""
    _, sig_path, _, _ = signed_build

    raw = base64.b64decode(sig_path.read_bytes())

    assert len(raw) == 64


def test_the_signature_verifies_over_the_exact_binary_bytes(signed_build):
    """Signed over the file's bytes as-is — not a digest of them, not a
    canonicalised form. `VerifySignature` passes `os.ReadFile(binaryPath)`
    straight to `ed25519.Verify`."""
    binary, sig_path, raw_public, _ = signed_build

    public = ed25519.Ed25519PublicKey.from_public_bytes(raw_public)
    public.verify(base64.b64decode(sig_path.read_bytes()), binary.read_bytes())


def test_a_tampered_binary_fails_the_same_check(signed_build):
    binary, sig_path, raw_public, _ = signed_build
    binary.write_bytes(b"malicious contents")

    public = ed25519.Ed25519PublicKey.from_public_bytes(raw_public)
    with pytest.raises(Exception):  # InvalidSignature
        public.verify(base64.b64decode(sig_path.read_bytes()), binary.read_bytes())


def test_the_manifest_records_the_signature_beside_the_digest(signed_build):
    _, _, _, tmp_path = signed_build

    manifest = json.loads((tmp_path / "manifest.json").read_text())

    assert manifest["1.0.0"]["linux-amd64.sig"] == "cb-agent-linux-amd64.sig"
    # And the digest entry is still a digest, not the signature filename —
    # the `.sig` guard in the digest loop is what keeps those apart.
    assert len(manifest["1.0.0"]["linux-amd64"]) == 64


def test_an_unsigned_build_still_produces_a_manifest(tmp_path):
    """`make build-from-source` runs with no key and must keep working: a
    self-hoster has no access to the release private key."""
    dist = tmp_path / "1.0.0"
    dist.mkdir()
    (dist / "cb-agent-linux-amd64").write_bytes(b"fake agent binary contents")

    env = {k: v for k, v in os.environ.items() if k != "AGENT_SIGNING_PRIVATE_KEY"}
    result = subprocess.run(
        [sys.executable, str(GEN_MANIFEST), str(dist), "1.0.0"],
        check=True,
        env=env,
        capture_output=True,
        text=True,
    )

    assert "warn mode" in result.stderr
    assert not list(dist.glob("*.sig"))
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["1.0.0"]["linux-amd64"]
