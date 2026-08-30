"""B3: the backup artifact that leaves the host must be opaque, and provably so.

The release blocker is "backup artifacts that leave the host (S3) are encrypted;
the vault key never leaves in plaintext".  The implementation landed before this
file did, and it was correct — but it was not *exercisable*.  Every unit test of
``age_encryption`` replaces ``subprocess.run`` with a stub, so nothing anywhere
had run ``age``, produced a real derivative, or opened one again; and the only
caller that could produce an encrypted snapshot was the scheduled S3 upload, so
neither a verification tier nor an operator could take the round trip at all.

What closes the blocker is `t3::exercise_encrypted_snapshot_roundtrip` in
`scripts/ci/tier3-artifact.sh`, which creates a real encrypted snapshot on a
packaged install and restores from it.  This file is the cheap half: the static
facts that tier depends on, each of which fails silently if it drifts.

  * The tier needs `age` on the guest.  Nothing installs it there — the package
    depends on it.  Drop the dependency and the tier fails with "age is not on
    PATH", which reads as an infrastructure problem and is a product one.
  * The tier drives the product's own encryptor through the packaged binary.  A
    second encryptor — a bare `age --encrypt` in the shell, say — would let the
    tier pass while the code path that actually runs in production diverged.
  * A `.age` archive with no identity must be refused rather than half-applied.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
NFPM = REPO_ROOT / "nfpm.yaml"
CB = REPO_ROOT / "cb"
ROLLBACK = REPO_ROOT / "packaging/rollback.sh"
TIER3 = REPO_ROOT / "scripts/ci/tier3-artifact.sh"
CLI = REPO_ROOT / "apps/backend/src/app/cli.py"
START = REPO_ROOT / "apps/backend/src/app/start.py"
AGE_ENCRYPTION = REPO_ROOT / "apps/backend/src/app/services/backup/age_encryption.py"
BACKEND_APP = REPO_ROOT / "apps/backend/src/app"


# ── the runtime prerequisite ────────────────────────────────────────────────


def test_age_is_a_hard_dependency_of_the_deb_and_the_rpm():
    """Not a recommends.

    A weak dependency can be declined, and an operator who declines it gets an
    install whose S3 backup fails closed at 02:00 with a message about a missing
    executable.  `age` is not an optional convenience here: it is the whole of
    how the vault key stops travelling in the clear.
    """
    import yaml

    config = yaml.safe_load(NFPM.read_text(encoding="utf-8"))
    overrides = config["overrides"]
    for fmt in ("deb", "rpm"):
        depends = overrides[fmt].get("depends") or []
        assert "age" in depends, (
            f"nfpm.yaml's {fmt} override does not depend on `age`. Without it an "
            f"encrypted backup cannot be produced on that platform, and the failure "
            f"lands on the operator at backup time rather than at install time."
        )
        recommends = overrides[fmt].get("recommends") or []
        assert "age" not in recommends, (
            f"`age` appears in {fmt} recommends, which a package manager may be "
            f"configured to skip. It belongs in depends."
        )


# ── one encryptor ───────────────────────────────────────────────────────────


def test_the_backend_encrypts_with_age_in_exactly_one_module():
    encryptors = {
        str(path.relative_to(REPO_ROOT))
        for path in sorted(BACKEND_APP.rglob("*.py"))
        if '"--encrypt"' in path.read_text(encoding="utf-8")
    }
    assert encryptors == {"apps/backend/src/app/services/backup/age_encryption.py"}, (
        f"`age --encrypt` is invoked from {sorted(encryptors)}. B3's promise is a "
        f"property of every artifact that leaves the host, and it can only be "
        f"reasoned about while there is one place that produces them."
    )


def test_the_encryptor_takes_a_public_recipient_and_never_an_identity():
    """The custody half of B3.

    The operator holds the private identity.  If this module ever learned to read
    one, the host would hold both halves and the encrypted copy would stop being
    a boundary at all.
    """
    text = AGE_ENCRYPTION.read_text(encoding="utf-8")
    assert '"--recipient"' in text, "the encryptor must name its recipient explicitly"
    assert "--identity" not in text, (
        "age_encryption.py references --identity. The host encrypts to a public "
        "key and must never be able to decrypt what it uploaded."
    )


def test_the_shell_never_encrypts_on_its_own():
    """`cb backup --encrypt-to` must reach the product encryptor, not re-implement it."""
    text = CB.read_text(encoding="utf-8")
    assert "--snapshot-encrypt" in text, (
        "cb does not reach the packaged binary's --snapshot-encrypt entry point. A "
        "packaged host has no `python -m app.cli`, so that flag is the only route in."
    )
    assert "snapshot encrypt --recipient" in text, (
        "cb does not reach `app.cli snapshot encrypt` in container mode"
    )
    assert not re.search(r"age\s+--encrypt", text), (
        "cb shells out to `age --encrypt` directly. That is a second encryptor, and "
        "the one the tier exercises would stop being the one production runs."
    )


# ── the entry points the tier and the operator use ──────────────────────────


def test_the_packaged_binary_exposes_snapshot_encrypt():
    text = START.read_text(encoding="utf-8")
    assert '"--snapshot-encrypt" in arguments' in text, (
        "start.py does not handle --snapshot-encrypt. `cb backup --encrypt-to` on a "
        "deb/rpm install has no other way to reach the encryptor."
    )
    assert '["snapshot", "encrypt"' in text or '"snapshot", "encrypt"' in text, (
        "--snapshot-encrypt must dispatch to app.cli's `snapshot encrypt`"
    )


def test_the_cli_requires_a_recipient():
    text = CLI.read_text(encoding="utf-8")
    match = re.search(
        r'add_parser\(\s*\n?\s*"encrypt".*?encrypt\.add_argument\(\s*\n?\s*"--recipient",\s*\n?\s*required=True',
        text,
        re.DOTALL,
    )
    assert match, (
        "`cb snapshot encrypt` must require --recipient. Defaulting it would mean an "
        "archive encrypted to a key nobody chose, which is indistinguishable from one "
        "encrypted to a key nobody holds."
    )


def test_both_restore_paths_refuse_an_encrypted_archive_without_an_identity():
    """`cb restore` and `circuit-breaker-rollback` are the two documented ways in.

    An operator reaching for either during a recovery must be told what is missing,
    not dropped into a decrypt failure or, worse, a partial restore.
    """
    for path in (CB, ROLLBACK):
        text = path.read_text(encoding="utf-8")
        assert "== *.age" in text, f"{path.name} does not branch on the .age extension"
        assert "--identity" in text, f"{path.name} does not accept --identity"
        assert re.search(
            r"require.*--identity|--identity.*require", text, re.IGNORECASE
        ), (
            f"{path.name} does not refuse an encrypted archive that arrives without "
            f"an identity"
        )


# ── the tier that turns all of the above into evidence ──────────────────────


def test_tier3_takes_the_encrypted_round_trip_on_install_rows():
    text = TIER3.read_text(encoding="utf-8")
    assert "t3::exercise_encrypted_snapshot_roundtrip" in text, (
        "tier3-artifact.sh no longer runs the encrypted backup round trip. B3 closes "
        "on that assertion; without it the blocker's evidence is a unit test that "
        "stubs out the encryption."
    )
    # Called, not merely defined. A function nothing invokes is the "gate that
    # passes by not running" ADR 0005 forbids.
    calls = re.findall(
        r"^\s*t3::exercise_encrypted_snapshot_roundtrip\s*$", text, re.MULTILINE
    )
    assert calls, (
        "t3::exercise_encrypted_snapshot_roundtrip is defined but never called"
    )


def test_tier3_asserts_both_halves_of_the_promise():
    """Opacity and recoverability.

    Either one alone is satisfiable by a broken implementation: an empty file
    contains no vault key, and an unencrypted tarball restores perfectly.
    """
    text = TIER3.read_text(encoding="utf-8")
    assert "the vault key appears in plaintext inside" in text, (
        "the tier does not assert that the derivative is free of the host's vault key"
    )
    assert "the local snapshot does not carry the host's vault key" in text, (
        "the tier does not assert its own control -- that the key it searches the "
        "ciphertext for is present in the plaintext archive. Without that, the "
        "negative result is also what a truncated or empty derivative produces."
    )
    assert "the known record did not survive the encrypted restore" in text, (
        "the tier does not assert that a known record survives the encrypted restore"
    )
    assert "the post-snapshot row survived the restore" in text, (
        "the tier does not assert that the restore actually replaced the database; "
        "without it a restore that did nothing at all passes"
    )
    assert "accepted an unrelated age identity" in text, (
        "the tier does not assert that a wrong identity is refused"
    )
