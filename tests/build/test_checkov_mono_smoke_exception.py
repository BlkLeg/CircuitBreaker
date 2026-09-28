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
  (c) the skip reaches any other workflow file;
  (d) any caller other than dev-ci.yml:build-docker grants `packages: write` or
      passes `publish: true` to mono-smoke.yml — CHECKOV-001's reason rests on
      "only dev-ci.yml's caller grants packages: write / publish: true", and
      until this test existed nothing checked that claim stayed true.
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


# ── "only dev-ci.yml publishes" is the reason CHECKOV-001 gives; enforce it ──
#
# mono-smoke.yml declares no `permissions:` (see
# test_mono_smoke_still_declares_no_permissions_anywhere above), so its jobs
# push or don't push depending only on what the calling job grants and passes.
# CHECKOV-001's `reason` states that only dev-ci.yml's `build-docker` caller
# grants `packages: write` and turns on `publish: true`. Nothing checked that
# claim stayed true; this does.
MONO_SMOKE_USES = "./.github/workflows/mono-smoke.yml"
EXPECTED_PUBLISHER = "dev-ci.yml:build-docker"


def _mono_smoke_callers(workflows_dir: Path = WORKFLOWS) -> dict[str, dict]:
    """Every job, in every workflow file directly under `workflows_dir`, whose
    `uses:` points at mono-smoke.yml — keyed `<file>:<job_id>`."""
    callers: dict[str, dict] = {}
    for path in sorted([*workflows_dir.glob("*.yml"), *workflows_dir.glob("*.yaml")]):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for job_id, job in (workflow.get("jobs") or {}).items():
            if str((job or {}).get("uses", "")) == MONO_SMOKE_USES:
                callers[f"{path.name}:{job_id}"] = job or {}
    return callers


def _single_publisher_violations(callers: dict[str, dict]) -> list[str]:
    """CHECKOV-001's claim, made mechanical. Returns one message per caller
    that breaks it; an empty list means the claim holds for `callers`."""
    problems: list[str] = []

    publishers = {
        where for where, job in callers.items()
        if (job.get("with") or {}).get("publish") is True
    }
    if publishers != {EXPECTED_PUBLISHER}:
        problems.append(
            f"publish: true is passed by {sorted(publishers)}, expected only {EXPECTED_PUBLISHER!r} to pass it"
        )

    writers = {
        where for where, job in callers.items()
        if str((job.get("permissions") or {}).get("packages", "")) == "write"
    }
    if writers != {EXPECTED_PUBLISHER}:
        problems.append(
            f"packages: write is granted by {sorted(writers)}, expected only {EXPECTED_PUBLISHER!r} to grant it"
        )

    for where, job in callers.items():
        if where == EXPECTED_PUBLISHER:
            continue
        scope = (job.get("permissions") or {}).get("packages")
        if scope is not None:
            problems.append(f"{where} grants packages: {scope!r}; only {EXPECTED_PUBLISHER} may")
        if "publish" in (job.get("with") or {}):
            problems.append(f"{where} sets publish: {(job['with'])['publish']!r}; only {EXPECTED_PUBLISHER} may set it")

    return problems


def test_at_least_two_callers_of_mono_smoke_are_found():
    """Positive control: guards the checks below against passing vacuously
    because the parser stopped finding callers."""
    callers = _mono_smoke_callers()
    assert len(callers) >= 2, callers
    assert "dev-ci.yml:build-docker" in callers
    assert "tier2.yml:mono" in callers


def test_only_dev_ci_may_publish_through_mono_smoke():
    problems = _single_publisher_violations(_mono_smoke_callers())
    assert not problems, "\n".join(problems)


def test_a_second_publisher_through_mono_smoke_is_caught():
    """Positive control for test_only_dev_ci_may_publish_through_mono_smoke:
    proves the check actually fails once a second caller starts publishing,
    rather than passing no matter what it is given."""
    rogue = dict(_mono_smoke_callers())
    rogue["rogue-workflow.yml:rogue-job"] = {
        "uses": MONO_SMOKE_USES,
        "permissions": {"contents": "read", "packages": "write"},
        "with": {"publish": True},
    }

    problems = _single_publisher_violations(rogue)

    assert problems, "a second publisher through mono-smoke.yml must be caught"
    assert any("rogue-workflow.yml:rogue-job" in p for p in problems)
