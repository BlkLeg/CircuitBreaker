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

Four things are asserted, because each one has failed differently before:

1. No planted secret — the env file, the DB URL password, or the install
   log's JWT secret — survives into any file inside the bundle.
2. A long input is not silently truncated to 500 characters: a secret planted
   well past that point is redacted AND the content after it still exists.
3. `cb diag bundle` fails closed with no python3 on PATH: it must refuse to
   write a bundle at all, and exit non-zero, rather than ship logs in the
   clear.
4. `_redact_evidence` — the helper `cb doctor` uses for its own evidence
   field, on both the pass branch and the fail branch — catches the same
   credential shapes `_redact_stream` does, and doctor.json (copied into the
   bundle verbatim) never carries a passing check's raw evidence.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
import tarfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CB = REPO_ROOT / "deploy" / "cli" / "cb"
ROOT_CB = REPO_ROOT / "cb"

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


def _run_bundle(
    root: Path,
    output: Path,
    *,
    path: str = "/usr/bin:/bin",
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {"PATH": path, "CB_ROOT_PREFIX": str(root)}
    env.update(extra_env or {})
    return subprocess.run(
        ["bash", str(CB), "diag", "bundle", "--output", str(output)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _call_redact_evidence(text: str, *, cb: Path = CB) -> str:
    """Invoke the real `_redact_evidence` from the shipped CLI, in isolation.

    Sources the script (its own stdout redirected away, so the top-level
    identity load and the `help` the bare dispatcher falls through to don't
    contaminate what we capture) and then calls the function directly with
    the candidate text via an env var, never a positional arg, so nothing
    leaks into the script's own `case "${1:-help}"` dispatch.
    """
    completed = subprocess.run(
        ["bash", "-c", 'source "$CB_PATH" >/dev/null 2>&1; _redact_evidence "$CB_TEST_INPUT"'],
        capture_output=True,
        text=True,
        env={
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "CB_PATH": str(cb),
            "CB_TEST_INPUT": text,
        },
        check=True,
    )
    return completed.stdout


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


# ── _redact_evidence: same credential shapes as _redact_stream ─────────────
#
# _redact_evidence backs `cb doctor`'s evidence field (short tails, truncated
# to 500 characters) and, before this fix, still carried the old narrow
# regexes that _redact_stream itself was widened away from in 89fbe686:
# (PASSWORD|TOKEN|SECRET|VAULT_KEY|JWT)=\S+ and a fixed scheme alternation
# requiring at least one userinfo character. Both functions must now catch
# the identical shapes.
EVIDENCE_SHAPE_PLANTED = {
    "http_scheme": (
        "connecting to http://proxyuser:PLANTEDPROXYPW@10.0.0.1:3128 failed",
        "PLANTEDPROXYPW",
    ),
    "compound_scheme": (
        "dsn=postgresql+asyncpg://breaker:PLANTEDDBPW@127.0.0.1:6432/circuitbreaker",
        "PLANTEDDBPW",
    ),
    "empty_userinfo": (
        "CB_REDIS_URL=redis://:PLANTEDREDISPW@127.0.0.1:6379/0",
        "PLANTEDREDISPW",
    ),
    "key_only": (
        "CB_REDIS_PASSWORD=PLANTEDREDISPLAIN",
        "PLANTEDREDISPLAIN",
    ),
}


@pytest.mark.parametrize(
    ("shape", "value"),
    EVIDENCE_SHAPE_PLANTED.values(),
    ids=EVIDENCE_SHAPE_PLANTED.keys(),
)
def test_redact_evidence_catches_the_shapes_redact_stream_needed_widening_for(
    shape: str, value: str
) -> None:
    marker = re.search(r"PLANTED[A-Z]+", value)
    assert marker is not None
    output = _call_redact_evidence(shape)
    assert value not in output, (
        f"_redact_evidence left a credential unredacted: input={shape!r} output={output!r}"
    )
    assert marker.group(0) not in output, (
        f"_redact_evidence left a credential unredacted: input={shape!r} output={output!r}"
    )


def test_redact_evidence_truncation_is_unchanged() -> None:
    """The 500-character bound is deliberate for short doctor evidence tails
    and is not the defect this suite guards against — only the patterns
    changed. A regression that also widens or drops the truncation should
    fail here, separately from the pattern-matching tests above.
    """
    long_text = "x" * 600
    output = _call_redact_evidence(long_text)
    assert len(output) == 500


# ── doctor.json: the pass branch must redact too ────────────────────────────
#
# Before this fix, `_run_check`'s pass branch stored a passing probe's raw
# stdout/stderr straight into doctor.json's evidence field with no call to
# _redact_evidence at all — only the fail branch redacted. cmd_diag_bundle
# copies doctor.json into the bundle verbatim on the strength of a comment
# claiming "cb doctor already redacts its own evidence via _redact_evidence",
# which was true for only half the code path. This drives a real `cb doctor
# --json` pass-branch check (binary mode's "selftest", which succeeds when
# the configured binary exits 0) through a fake binary that echoes a
# connection string on success — a realistic shape, e.g. a selftest that
# logs the DSN it last used — and asserts the planted secret never reaches
# doctor.json inside the bundle.
def test_doctor_json_pass_branch_is_redacted_in_the_bundle(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture"
    fixture.mkdir()

    identity = fixture / "install-identity.json"
    identity.write_text(
        '{"schema_version": 1, "mode": "package", "version": "0.4.2", '
        '"installed_at": "2026-09-20T00:00:00Z"}\n'
    )

    fake_binary = fixture / "fake-circuit-breaker"
    fake_binary.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$1" == "--selftest" ]]; then\n'
        '  echo "selftest ok; last conn was '
        "postgresql://breaker:PLANTEDDOCTORPASSPW@127.0.0.1:5432/circuitbreaker\"\n"
        "  exit 0\n"
        "fi\n"
        "exit 1\n"
    )
    fake_binary.chmod(fake_binary.stat().st_mode | stat.S_IEXEC)

    root = tmp_path / "root"
    root.mkdir()

    output = tmp_path / "bundle.tar.gz"
    completed = _run_bundle(
        root,
        output,
        extra_env={
            "CB_IDENTITY_PATH": str(identity),
            "CB_BINARY": str(fake_binary),
        },
    )
    assert output.exists(), (
        "cb diag bundle produced no file:\n" + completed.stdout + completed.stderr
    )

    with tarfile.open(output) as handle:
        member = handle.getmember("doctor.json")
        extracted = handle.extractfile(member)
        assert extracted is not None
        doctor_json = extracted.read().decode("utf-8", errors="replace")

    assert '"status": "pass"' in doctor_json, (
        "fixture did not exercise a pass-branch doctor check — test setup is broken:\n"
        + doctor_json
    )
    assert "PLANTEDDOCTORPASSPW" not in doctor_json, (
        "a passing doctor check's raw evidence leaked a credential into "
        "doctor.json inside the bundle: " + doctor_json
    )
    assert "[REDACTED]" in doctor_json, (
        "expected the pass-branch selftest evidence to show as redacted, not "
        "merely absent:\n" + doctor_json
    )


# ── the two redaction functions cannot diverge a third time ────────────────
def test_redact_functions_share_pattern_set() -> None:
    """`_redact_stream` and `_redact_evidence` must draw from one pattern set.

    This is what closed the first two holes (89fbe686) and stayed open for a
    third (`_redact_evidence` kept the old regexes inline instead of sharing
    `_redact_stream`'s). Both now call the same `_redact_pattern_source`
    helper for their substitution logic — assert that helper exists exactly
    once and that both functions invoke it, so a future edit that inlines a
    pattern into just one of them fails the build instead of shipping a
    silent gap.
    """
    for script in (CB, ROOT_CB):
        text = script.read_text()

        definitions = re.findall(r"^_redact_pattern_source\(\) \{", text, flags=re.MULTILINE)
        assert len(definitions) == 1, (
            f"{script}: expected exactly one _redact_pattern_source definition, "
            f"found {len(definitions)} — the shared pattern set must not be "
            "duplicated"
        )

        evidence_match = re.search(
            r"_redact_evidence\(\) \{.*?\n\}\n", text, flags=re.DOTALL
        )
        stream_match = re.search(
            r"_redact_stream\(\) \{.*?\n\}\n", text, flags=re.DOTALL
        )
        assert evidence_match is not None, f"{script}: _redact_evidence not found"
        assert stream_match is not None, f"{script}: _redact_stream not found"

        assert "_redact_pattern_source" in evidence_match.group(0), (
            f"{script}: _redact_evidence no longer calls the shared "
            "_redact_pattern_source helper — it may carry its own inline "
            "copy of the patterns again"
        )
        assert "_redact_pattern_source" in stream_match.group(0), (
            f"{script}: _redact_stream no longer calls the shared "
            "_redact_pattern_source helper — it may carry its own inline "
            "copy of the patterns again"
        )

    # And the two CLI copies must still be byte-identical, patterns included.
    assert CB.read_text() == ROOT_CB.read_text(), (
        "deploy/cli/cb and the repo-root cb have diverged — they are held "
        "byte-identical by test_cb_cli_parity.py"
    )
