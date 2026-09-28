"""The one checkov exception stays one file, one check, and stays true.

mono-smoke.yml declares no `permissions:` at any level, on purpose: its jobs
inherit the CALLING job's GITHUB_TOKEN grant, so dev-ci's `packages: write`
reaches the push while tier2, the release and the release dry run, which grant
read only, cannot push at all (Tier 2 slice A3, maintainer decision 1). checkov
reads an absent block as `write-all` and fails CKV2_GHA_1, and checkov cannot
apply an inline `checkov:skip` to a graph check. So the exception is made in
the scanner invocation, in two places that must agree (CI and the local gate,
P1), and is governed by one manifest row (CHECKOV-001).

CLAUDE.md rule 5: things pinned in more than one place move together, and the
guard is added with the pairing. This is that guard. It fails when:
  (a) security.yml, scripts/security_scan.sh and the manifest stop naming the
      same single file and the same single check;
  (b) mono-smoke.yml gains a `permissions:` block anywhere — the suppression's
      justification is then false, and the suppression must be removed;
  (c) the skip reaches any other workflow file.
"""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
SECURITY_YML = WORKFLOWS / "security.yml"
LOCAL_GATE = REPO_ROOT / "scripts" / "security_scan.sh"
MANIFEST = REPO_ROOT / "specs" / "1.0.0" / "release-control" / "security-suppressions.json"

EXCEPTED_FILE = ".github/workflows/mono-smoke.yml"
EXCEPTED_CHECK = "CKV2_GHA_1"
SKIP_PATH = r"(^|/)\.github/workflows/mono-smoke\.yml$"


def _checkov_commands(text: str) -> list[list[str]]:
    """Every `checkov` scan invocation in `text`, tokenised (the `--version`
    probe excluded), regardless of what order its flags appear in.

    R2 (A3 controller ruling): the previous parser only recognised an
    invocation whose FIRST argument was `-d`/`-f`, so a reordered call such as
    `checkov --skip-check CKV2_GHA_1 -d .github/workflows/` slipped past every
    assertion below it. This finds every `checkov` invocation first, then
    tokenises the whole thing and reads `-d`/`-f`, `--skip-path` and
    `--skip-check` out of it wherever they land.
    """
    commands: list[list[str]] = []
    for line in text.splitlines():
        match = re.search(r"(?:^|[\s/\"])checkov\s+(\S.*)$", line)
        if not match:
            continue
        body = match.group(1).split(">>")[0].split("||")[0]
        try:
            tokens = shlex.split(body)
        except ValueError:
            continue
        if not tokens or "--version" in tokens:
            continue
        if not ({"-d", "-f"} & set(tokens)):
            continue
        commands.append(tokens)
    return commands


def _flag_values(command: list[str], flag: str) -> list[str]:
    return [command[i + 1] for i, token in enumerate(command[:-1]) if token == flag]


def _sources() -> dict[str, list[list[str]]]:
    workflow = yaml.safe_load(SECURITY_YML.read_text(encoding="utf-8"))
    runs = "\n".join(
        str(step.get("run", "")) for step in workflow["jobs"]["checkov"]["steps"] if isinstance(step, dict)
    )
    return {
        "security.yml": _checkov_commands(runs),
        "scripts/security_scan.sh": _checkov_commands(LOCAL_GATE.read_text(encoding="utf-8")),
    }


def test_the_parser_finds_both_scans_in_both_places():
    """Guards against the checks below passing vacuously."""
    for where, commands in _sources().items():
        assert any("-d" in c for c in commands), f"{where}: no directory scan found"
        assert any("-f" in c for c in commands), f"{where}: no mono-smoke.yml scan found"


def test_ci_and_the_local_gate_make_the_same_single_exception():
    for where, commands in _sources().items():
        skip_paths = {v for c in commands for v in _flag_values(c, "--skip-path")}
        skip_checks = {v for c in commands for v in _flag_values(c, "--skip-check")}
        assert skip_paths == {SKIP_PATH}, f"{where} skips paths {skip_paths}"
        assert skip_checks == {EXCEPTED_CHECK}, f"{where} skips checks {skip_checks}"
        for command in commands:
            if ".github/workflows/" in _flag_values(command, "-d"):
                assert SKIP_PATH in _flag_values(command, "--skip-path"), (
                    f"{where}: the workflow directory scan must skip only {EXCEPTED_FILE}"
                )
            if "--skip-check" in command:
                assert _flag_values(command, "-f") == [EXCEPTED_FILE] and "-d" not in command, (
                    f"{where}: --skip-check {EXCEPTED_CHECK} may only scan {EXCEPTED_FILE}"
                )
        # The excepted file is still scanned, with every other check.
        assert any(
            _flag_values(c, "-f") == [EXCEPTED_FILE] and _flag_values(c, "--skip-check") == [EXCEPTED_CHECK]
            for c in commands
        ), f"{where} never scans {EXCEPTED_FILE} on its own"


def test_the_manifest_governs_exactly_this_exception():
    rows = json.loads(MANIFEST.read_text(encoding="utf-8"))["suppressions"]
    checkov = [row for row in rows if row["tool"] == "checkov"]
    assert [row["selector"] for row in checkov] == [f"{EXCEPTED_FILE}:{EXCEPTED_CHECK}"], checkov


def test_mono_smoke_still_declares_no_permissions_anywhere():
    """If this fails, the exception's justification is gone: remove the
    --skip-path / --skip-check split from security.yml and security_scan.sh and
    the CHECKOV-001 manifest row, and let CKV2_GHA_1 scan mono-smoke.yml again."""
    workflow = yaml.safe_load((REPO_ROOT / EXCEPTED_FILE).read_text(encoding="utf-8"))
    assert "permissions" not in workflow
    for job_id, job in (workflow.get("jobs") or {}).items():
        assert "permissions" not in (job or {}), f"mono-smoke.yml:{job_id} declares permissions"


def test_the_skip_path_matches_no_other_workflow():
    pattern = re.compile(SKIP_PATH)
    workflows = sorted([*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")])
    matched = [p.name for p in workflows if pattern.search(p.relative_to(REPO_ROOT).as_posix())]
    assert matched == ["mono-smoke.yml"], matched
    # checkov also skips any path that CONTAINS the literal value; the regex
    # metacharacters make that impossible for a real file name.
    assert not any(SKIP_PATH in p.relative_to(REPO_ROOT).as_posix() for p in workflows)


def test_the_parser_catches_a_reordered_invocation_that_widens_the_skip():
    """R2: a checkov call whose flags are reordered so `-d`/`-f` is not the
    first argument — e.g. `checkov --skip-check CKV2_GHA_1 -d
    .github/workflows/` — would widen the CKV2_GHA_1 suppression from
    mono-smoke.yml alone to the entire workflows tree. This is not a real
    invocation in this repo; it proves the parser sees it (and so
    test_ci_and_the_local_gate_make_the_same_single_exception would reject it,
    since a `-d` scan without a matching `--skip-path` fails that test)."""
    reordered = "checkov --skip-check CKV2_GHA_1 -d .github/workflows/"
    commands = _checkov_commands(reordered)
    assert commands, "parser did not recognise a reordered checkov invocation"
    [command] = commands
    assert _flag_values(command, "-d") == [".github/workflows/"]
    assert _flag_values(command, "--skip-check") == [EXCEPTED_CHECK]
    # The widening itself: a directory scan carrying --skip-check instead of
    # the required --skip-path, which is exactly what
    # test_ci_and_the_local_gate_make_the_same_single_exception's per-command
    # loop rejects.
    assert not _flag_values(command, "--skip-path")


def test_no_workflow_carries_an_inline_skip_for_the_check():
    """An inline skip does nothing for a graph check today and would widen the
    exception silently the day checkov starts honouring it."""
    offenders = [
        p.name for p in sorted(WORKFLOWS.glob("*.y*ml"))
        if re.search(rf"checkov:skip={EXCEPTED_CHECK}\b", p.read_text(encoding="utf-8"))
    ]
    assert not offenders, offenders
