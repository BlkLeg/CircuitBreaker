"""Nothing secret may survive into a bundle meant for a public issue.

`cb diag bundle` exists so an operator can hand over one file. That makes it the
highest-risk artifact in the installer design: everything it collects —
/etc/circuitbreaker/.env, journal output, the install log — has held a JWT
secret, a vault key or a database password at some point.

The redaction is not new here. cb_env_redacted already masks secrets and
credentials embedded in connection URLs, and the CLI has its own helpers. This
suite asserts the bundle actually uses them, against planted values, because a
redaction that is called on three of four inputs looks identical to one that
works.

Three things are asserted, because each one has failed differently before:

1. No planted secret — the env file, the DB URL password, or the install
   log's JWT secret — survives into any file inside the bundle.
2. A long input is not silently truncated to 500 characters: a secret planted
   well past that point is redacted AND the content after it still exists.
3. `cb diag bundle` fails closed with no python3 on PATH: it must refuse to
   write a bundle at all, and exit non-zero, rather than ship logs in the
   clear.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
import tarfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CB = REPO_ROOT / "deploy" / "cli" / "cb"

# Planted values. Distinctive enough that a hit is unambiguous, and generated
# shapes rather than realistic-looking credentials.
PLANTED = {
    "CB_JWT_SECRET": "PLANTEDJWTSECRETdeadbeefdeadbeefdeadbeef",
    "CB_VAULT_KEY": "PLANTEDVAULTKEYdeadbeefdeadbeefdeadbeefAA=",
    "CB_DB_PASSWORD": "PLANTEDDBPASSWORDdeadbeef",
}

# A second secret, distinct from the ones above, used only to prove that a
# long file is not truncated to _redact_evidence's 500-character bound.
LATE_SECRET_KEY = "CB_JWT_SECRET"
LATE_SECRET_VALUE = "PLANTEDLATESECRETdeadbeefdeadbeefdeadbeef"
TAIL_MARKER = "AFTER-CHARACTER-500-MARKER-STILL-PRESENT"


def _fake_install(root: Path) -> Path:
    etc = root / "etc" / "circuitbreaker"
    etc.mkdir(parents=True)
    env = "\n".join(f"{key}={value}" for key, value in PLANTED.items())
    env += (
        f"\nCB_DB_URL=postgresql://breaker:{PLANTED['CB_DB_PASSWORD']}"
        "@127.0.0.1:6432/circuitbreaker\n"
    )
    (etc / ".env").write_text(env)
    logs = root / "var" / "lib" / "circuitbreaker" / "logs"
    logs.mkdir(parents=True)
    (logs / "install.log").write_text(
        f"starting with CB_JWT_SECRET={PLANTED['CB_JWT_SECRET']}\n"
    )
    return root


def _run_bundle(root: Path, output: Path, *, path: str = "/usr/bin:/bin") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(CB), "diag", "bundle", "--output", str(output)],
        capture_output=True,
        text=True,
        env={"PATH": path, "CB_ROOT_PREFIX": str(root)},
        check=False,
    )


def test_no_planted_secret_appears_in_the_bundle(tmp_path: Path) -> None:
    root = _fake_install(tmp_path / "root")
    output = tmp_path / "bundle.tar.gz"
    completed = _run_bundle(root, output)
    assert output.exists(), (
        "cb diag bundle produced no file:\n" + completed.stdout + completed.stderr
    )

    leaked: list[str] = []
    with tarfile.open(output) as handle:
        for member in handle.getmembers():
            if not member.isfile():
                continue
            extracted = handle.extractfile(member)
            assert extracted is not None
            content = extracted.read().decode("utf-8", errors="replace")
            for name, value in PLANTED.items():
                if value in content:
                    leaked.append(f"{name} in {member.name}")
    assert not leaked, (
        "the diagnostic bundle contains unredacted secrets: "
        + "; ".join(leaked)
        + ". This file is meant to be pasted into a public issue."
    )


# Shapes that escaped both `_redact_stream` regexes before this fix, plus one
# key-only canary. Each one was chosen because the *old* regex provably could
# not match it — this is why the pre-existing three tests above all passed
# on the unpatched code: they only ever planted shapes the old regex already
# handled (a plain `postgresql://user:pass@` URL and a key that was exactly
# CB_JWT_SECRET/CB_VAULT_KEY/CB_DB_PASSWORD), so the suite never exercised the
# escape routes below.
URL_SHAPE_PLANTED = {
    # Empty userinfo: `[^:/@]+` in the old URL regex required at least one
    # userinfo character. deploy/setup.sh writes exactly this shape
    # (`redis://:${CB_REDIS_PASSWORD}@...`) into /etc/circuitbreaker/.env.
    "CB_REDIS_URL": "redis://:PLANTEDREDISPW@127.0.0.1:6379/0",
    # Compound scheme: the old alternation demanded `://` immediately after
    # one of a fixed list of scheme names, so "postgresql+asyncpg://" (what
    # apps/backend/src/app/db/async_session.py rewrites the DSN to) missed
    # entirely.
    "CB_DB_URL": (
        "postgresql+asyncpg://breaker:PLANTEDDBPW@127.0.0.1:5432/circuitbreaker"
    ),
    # http/https were not in the old scheme alternation at all.
    "CB_EGRESS_PROXY_URL": "http://proxyuser:PLANTEDPROXYPW@proxy.example:3128",
}

# A key-only canary: the old key regex's alternation was exactly
# (PASSWORD|TOKEN|SECRET|VAULT_KEY|JWT), so a key literally named
# CB_REDIS_PASSWORD *did* match it (it contains "PASSWORD"). This canary
# exists to guard the widened regex against a regression that narrows the
# alternation back down or breaks the unanchored, full-identifier match.
KEY_SHAPE_PLANTED_VALUE = "PLANTEDREDISPASSWORDVALUE"


def test_url_and_key_shapes_that_escaped_the_old_regex_are_redacted(
    tmp_path: Path,
) -> None:
    """Canaries for the three URL shapes CLAUDE-reviewed as escaping
    `_redact_stream`'s old regexes, plus a plain key=value canary.

    Mirrors the manual repro: plant all four shapes in the fake install's
    .env, run `cb diag bundle`, extract, and grep every file in the bundle
    for the `PLANTED[A-Z]+` token embedded in each planted value. None may
    survive.
    """
    root = tmp_path / "root"
    etc = root / "etc" / "circuitbreaker"
    etc.mkdir(parents=True)
    env_lines = [f"{key}={value}" for key, value in URL_SHAPE_PLANTED.items()]
    env_lines.append(f"CB_REDIS_PASSWORD={KEY_SHAPE_PLANTED_VALUE}")
    (etc / ".env").write_text("\n".join(env_lines) + "\n")

    logs = root / "var" / "lib" / "circuitbreaker" / "logs"
    logs.mkdir(parents=True)
    (logs / "install.log").write_text(
        "connection failed: " + URL_SHAPE_PLANTED["CB_DB_URL"] + "\n"
    )

    output = tmp_path / "bundle.tar.gz"
    completed = _run_bundle(root, output)
    assert output.exists(), (
        "cb diag bundle produced no file:\n" + completed.stdout + completed.stderr
    )

    survivors: list[str] = []
    with tarfile.open(output) as handle:
        for member in handle.getmembers():
            if not member.isfile():
                continue
            extracted = handle.extractfile(member)
            assert extracted is not None
            content = extracted.read().decode("utf-8", errors="replace")
            for hit in re.findall(r"PLANTED[A-Z]+", content):
                survivors.append(f"{hit} in {member.name}")
    assert not survivors, (
        "a credential shape that escapes the old _redact_stream regex "
        "survived into the bundle: " + "; ".join(survivors)
    )


def test_long_input_is_not_truncated_to_500_characters(tmp_path: Path) -> None:
    """_redact_evidence truncates to 500 characters. _redact_stream must not.

    Plants a secret, and a distinctive marker, both well past character 500 of
    install.log. A bundle built on the old truncate-then-redact helper would
    lose everything past character 500 — including the marker — and this
    would look identical to a working redaction unless something asserts the
    tail is still there.
    """
    root = tmp_path / "root"
    etc = root / "etc" / "circuitbreaker"
    etc.mkdir(parents=True)
    (etc / ".env").write_text("CB_DB_PASSWORD=irrelevant-for-this-test\n")

    logs = root / "var" / "lib" / "circuitbreaker" / "logs"
    logs.mkdir(parents=True)
    padding = "filler line to push past five hundred characters\n" * 20
    assert len(padding) > 500
    install_log = (
        padding
        + f"{LATE_SECRET_KEY}={LATE_SECRET_VALUE}\n"
        + f"{TAIL_MARKER}\n"
    )
    (logs / "install.log").write_text(install_log)

    output = tmp_path / "bundle.tar.gz"
    completed = _run_bundle(root, output)
    assert output.exists(), (
        "cb diag bundle produced no file:\n" + completed.stdout + completed.stderr
    )

    with tarfile.open(output) as handle:
        member = handle.getmember("install.log")
        extracted = handle.extractfile(member)
        assert extracted is not None
        content = extracted.read().decode("utf-8", errors="replace")

    assert LATE_SECRET_VALUE not in content, (
        "a secret planted past character 500 of install.log survived into the bundle"
    )
    assert TAIL_MARKER in content, (
        "content past character 500 of install.log did not survive into the bundle — "
        "the bundle truncated the stream instead of only redacting it"
    )


def test_fails_closed_with_no_python3(tmp_path: Path) -> None:
    """A missing interpreter must refuse the bundle, never ship it unredacted."""
    root = _fake_install(tmp_path / "root")

    # A PATH with no python3 on it at all — not even a stub that could
    # masquerade as one — and none of the other real tools removed, so any
    # failure is attributable to the missing interpreter alone.
    stub_bin = tmp_path / "stub-bin"
    stub_bin.mkdir()
    for real_dir in ("/usr/bin", "/bin"):
        for name in os.listdir(real_dir):
            if name.startswith("python"):
                continue
            link = stub_bin / name
            if not link.exists():
                try:
                    link.symlink_to(Path(real_dir) / name)
                except OSError:
                    pass

    output = tmp_path / "bundle.tar.gz"
    completed = _run_bundle(root, output, path=str(stub_bin))

    assert completed.returncode != 0, (
        "cb diag bundle exited 0 with no python3 on PATH — it must fail closed:\n"
        + completed.stdout
        + completed.stderr
    )
    assert not output.exists(), (
        "cb diag bundle wrote a bundle with no python3 on PATH — a missing "
        "interpreter must never degrade into shipping logs unredacted"
    )
