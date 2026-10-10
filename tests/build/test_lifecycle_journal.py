"""NPM-03/09/10: deploy/scripts/lifecycle-state.py, the native lifecycle state utility.

Three halves.

The contract: the utility is the native validator of
specs/install/lifecycle-contract.md, so it must agree with the coordinator's
(packages/cli/src/lifecycle-contract.js) on every shared fixture: the valid and
invalid documents, the canonical and digest vectors and the redaction vectors.
Its embedded copy of the schemas must equal the packed files, and it must stay
Python 3.9 source.

The journal: begin, checkpoint, inspect and list run as real processes under a
real host lock taken by deploy/lib/lifecycle.sh, over a disposable state root
reached through the CB_LIFECYCLE_ROOT seam. Fault injection replaces the
syscalls an atomic write is made of (in process, or by killing a driver process
at that exact call), and a file-size limit stands in for a full disk.

The control plane: the bundle carries the utility and the library, setup.sh
installs them outside the release tree, and uninstall leaves them and the
audit history alone.

The seam is refused as root by design (ruling R8), so as root the process
cases skip in place and one root-only case re-runs this module as an unused
uid over a temporary root that uid owns, exactly as test_lifecycle_lock.py does.
"""

from __future__ import annotations

import ast
import errno
import fcntl
import importlib.util
import io
import json
import os
import re
import resource
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
UTILITY = ROOT / "deploy" / "scripts" / "lifecycle-state.py"
LIB = ROOT / "deploy" / "lib" / "lifecycle.sh"
SCHEMAS = ROOT / "packages" / "cli" / "schemas"
FIXTURES = ROOT / "packages" / "cli" / "test" / "fixtures" / "lifecycle"
EXIT_CODES_JS = ROOT / "packages" / "cli" / "src" / "exit-codes.js"
SETUP_SH = ROOT / "deploy" / "setup.sh"
INSTALL_SH = ROOT / "install.sh"
UNINSTALL_SH = ROOT / "uninstall.sh"
KINDS = ("plan", "event", "result", "journal", "history")


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("lifecycle_state", UTILITY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LS = _load()


def _fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


VALID = _fixture("valid.json")
INVALID = _fixture("invalid.json")
VECTORS = _fixture("digest-vectors.json")
REDACTION = _fixture("redaction-vectors.json")


# --- The contract ----------------------------------------------------------------------------


def _pointer(path: str) -> list[str]:
    return [part.replace("~1", "/").replace("~0", "~") for part in path.split("/")[1:]]


def _case_text(case: dict[str, Any]) -> str:
    """The fixture's mutation language, as lifecycle-contract.test.js applies it."""
    base = next(v for v in VALID[case["kind"]] if v["name"] == case["base"])
    doc = json.loads(json.dumps(base["document"]))
    for path, value in case.get("set", {}).items():
        *parents, leaf = _pointer(path)
        node = doc
        for part in parents:
            node = node[int(part)] if isinstance(node, list) else node[part]
        if isinstance(node, list) and int(leaf) == len(node):
            node.append(value)  # JavaScript's arr[arr.length] = v
        elif isinstance(node, list):
            node[int(leaf)] = value
        else:
            node[leaf] = value
    for path in case.get("unset", []):
        *parents, leaf = _pointer(path)
        node = doc
        for part in parents:
            node = node[int(part)] if isinstance(node, list) else node[part]
        del node[leaf]
    # JSON.stringify: compact, non-ASCII literal, lone surrogates escaped.
    text = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    if "replace" in case:
        assert case["replace"][0] in text, case["name"]
        text = text.replace(case["replace"][0], case["replace"][1], 1)
    return case.get("prefix", "") + text


def _encode(text: str) -> bytes:
    return text.encode("utf-8", errors="surrogatepass")


def test_the_embedded_schemas_are_the_packed_schemas() -> None:
    for name in ("lifecycle-plan", "lifecycle-event", "lifecycle-result", "operation-journal"):
        packed = json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))
        assert LS._SCHEMAS[name] == packed, f"{name}: regenerate the embedded copy in {UTILITY.name}"
    assert set(LS._SCHEMAS) == {"lifecycle-plan", "lifecycle-event", "lifecycle-result", "operation-journal"}


def test_every_valid_fixture_parses_and_validates() -> None:
    for kind in KINDS:
        assert VALID[kind], kind
        for case in VALID[kind]:
            assert LS.validate_document(kind, case["document"]) == {"ok": True}, f"{kind}: {case['name']}"
            text = json.dumps(case["document"], ensure_ascii=False)
            assert LS.parse_document(kind, _encode(text)) == case["document"], f"{kind}: {case['name']}"


def test_every_invalid_fixture_is_refused_where_and_why_the_coordinator_refuses_it() -> None:
    for case in INVALID:
        with pytest.raises(LS.ContractError) as caught:
            LS.parse_document(case["kind"], _encode(_case_text(case)))
        error = caught.value
        label = f"{case['kind']}: {case['name']}: {error}"
        assert error.path == case["expect"]["path"], label
        assert re.search(case["expect"]["reason"], error.reason), label
        assert error.unsupported == (case.get("unsupported") is True), label


def test_canonical_text_and_plan_digests_match_the_vectors() -> None:
    for vector in VECTORS["canonical"]:
        assert LS.canonicalize(vector["value"]) == vector["canonical"], vector["name"]
    for vector in VECTORS["plans"]:
        assert LS.plan_digest(vector["plan"]) == vector["digest"], vector["name"]
        assert LS.canonicalize({k: v for k, v in vector["plan"].items() if k not in ("plan_digest", "presentation")}) \
            == vector["canonical"], vector["name"]


def test_every_rejected_vector_is_refused_before_validation() -> None:
    for vector in VECTORS["rejected"]:
        with pytest.raises(LS.ContractError) as caught:
            LS.parse_document("event", _encode(vector["text"]))
        assert "unsupported schema_version" not in caught.value.reason, vector["name"]


@pytest.mark.parametrize(
    ("label", "data"),
    [
        ("NaN", b'{"n":NaN}'),
        ("Infinity", b'{"n":Infinity}'),
        ("negative Infinity", b'{"n":-Infinity}'),
        ("byte order mark", b'\xef\xbb\xbf{"schema_version":1}'),
        ("UTF-16", '{"schema_version":1}'.encode("utf-16")),
        ("UTF-32", '{"schema_version":1}'.encode("utf-32")),
        ("deep nesting", b"[" * 5000 + b"]" * 5000),
    ],
)
def test_text_python_reads_more_leniently_than_json_parse_is_refused(label: str, data: bytes) -> None:
    # json.loads accepts NaN and Infinity, and auto-detects UTF-16/32 from bytes; JSON.parse does neither.
    with pytest.raises(LS.ContractError) as caught:
        LS.parse_document("event", data)
    assert caught.value.path == "", label
    assert "unsupported" not in caught.value.reason, label


def test_redaction_matches_the_vectors() -> None:
    for vector in REDACTION["vectors"]:
        options = vector.get("options", {})
        out = LS.redact_text(vector["input"], options.get("max_length", 4096), options.get("single_line", False))
        assert out == vector["output"], vector["name"]
        kind = "installed_version" if options.get("single_line") else "text"
        if out:
            assert LS.conforms("result", kind, out), vector["name"]


def test_a_date_in_the_first_century_is_a_real_date() -> None:
    # Both validators read years 0001-9999 as the proleptic Gregorian calendar.
    checkpoint = next(v["document"] for v in VALID["event"] if v["name"] == "checkpoint")
    event = dict(checkpoint, at="0050-02-28T00:00:00Z", operation_id="op-00500228-001")
    assert LS.validate_document("event", event) == {"ok": True}
    leap = dict(event, at="0004-02-29T00:00:00Z")
    assert LS.validate_document("event", leap) == {"ok": True}
    assert not LS.validate_document("event", dict(event, at="0100-02-29T00:00:00Z"))["ok"]


def test_the_exit_codes_are_the_clis() -> None:
    js = dict(re.findall(r"^\s+([A-Z]+): (\d+),$", EXIT_CODES_JS.read_text(), re.MULTILINE))
    assert {k: str(v) for k, v in LS.EXIT.items()} == js


def test_the_utility_is_python_3_9_standard_library_only() -> None:
    source = UTILITY.read_text(encoding="utf-8")
    tree = ast.parse(source, feature_version=(3, 9))
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in (node.names if isinstance(node, ast.Import) else [ast.alias(name=node.module or "")])
    }
    assert imported <= set(sys.stdlib_module_names), imported - set(sys.stdlib_module_names)
    assert "from __future__ import annotations" in source
    # 3.10+ runtime APIs that a 3.9 parser accepts but a 3.9 interpreter does not have.
    for api in (r"\bzip\([^)]*strict=", r"datetime\.UTC\b", r"\bisinstance\([^)]*\|", r"\bpairwise\b",
                r"\.bit_count\(", r"\baiter\(|\banext\("):
        assert not re.search(api, source), api
    assert source.startswith("#!/usr/bin/python3 -I\n")
    assert os.access(UTILITY, os.X_OK), "the utility is installed 0755 and must be executable in the tree"


def test_the_utility_stays_fully_typed_and_documented() -> None:
    # make lint globs scripts/ only, so this keeps ruling R13's bar for the one file outside it;
    # ruff (--target-version py39) and mypy --strict were run on it when it was written.
    tree = ast.parse(UTILITY.read_text(encoding="utf-8"))
    assert ast.get_docstring(tree), "module docstring"
    scopes: list[list[ast.stmt]] = [tree.body, *(n.body for n in tree.body if isinstance(n, ast.ClassDef))]
    for body in scopes:
        for node in body:
            if not isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                continue
            if not node.name.startswith("_"):
                assert ast.get_docstring(node), f"{node.name} has no docstring"
            if isinstance(node, ast.FunctionDef):
                arguments = [a for a in node.args.args + node.args.kwonlyargs if a.arg != "self"]
                arguments += [a for a in (node.args.vararg, node.args.kwarg) if a is not None]
                assert node.returns is not None, f"{node.name} has no return annotation"
                assert all(a.annotation is not None for a in arguments), f"{node.name} has an unannotated argument"


# --- Requests that never reach the tree ------------------------------------------------------


def _run_inprocess(request: bytes) -> tuple[int, str, str]:
    out: list[str] = []
    err: list[str] = []
    code = LS.run(io.BytesIO(request), out.append, err.append)
    return code, "".join(out), "".join(err)


@pytest.mark.parametrize(
    ("label", "request_bytes", "message"),
    [
        ("not JSON", b"begin please", "not valid JSON"),
        ("empty", b"", "empty"),
        ("not an object", b"[]", "object"),
        ("unknown request", b'{"request":"delete"}', "request must be one of"),
        ("unknown member", b'{"request":"list","path":"/etc"}', "path is not a member of a list request"),
        ("secret member", b'{"request":"list","vault_key":"x"}', "secret field"),
        ("duplicate member", b'{"request":"list","request":"list"}', "duplicate key"),
        ("fraction", b'{"request":"checkpoint","expected_generation":1.0}', "safe integer"),
        ("missing member", b'{"request":"inspect"}', "needs operation_id"),
        ("malformed operation", b'{"request":"inspect","operation_id":"../../etc"}', "operation id"),
        ("oversized", b'{"request":"list","pad":"' + b"x" * 70000 + b'"}', "at most 65536 bytes"),
        ("overlong text", json.dumps({"request": "checkpoint", "operation_id": "op-20261001-001",
                                      "expected_generation": 1, "state": "committed",
                                      "error_reason": "x" * 4097}).encode(), "error_reason is not a valid text"),
    ],
)
def test_a_malformed_request_is_refused_with_2_before_the_tree_is_touched(
    label: str, request_bytes: bytes, message: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CB_LIFECYCLE_ROOT", str(tmp_path / "absent"))
    code, out, err = _run_inprocess(request_bytes)
    assert code == 2, (label, err)
    assert message in err, (label, err)
    assert out == ""
    assert not (tmp_path / "absent").exists()


def test_the_seam_is_refused_as_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CB_LIFECYCLE_ROOT", str(tmp_path))
    monkeypatch.setattr(LS.os, "geteuid", lambda: 0)
    code, _, err = _run_inprocess(b'{"request":"list"}')
    assert code == 2
    assert "test seam and is refused as root" in err


# --- The journal, through real processes and a real lock -------------------------------------

AS_ROOT = os.geteuid() == 0
seam = pytest.mark.skipif(
    AS_ROOT, reason="runs unprivileged: CB_LIFECYCLE_ROOT is refused as root (ruling R8); root re-runs it unprivileged"
)
DROP_UID = DROP_GID = 54321
root_only = pytest.mark.skipif(
    not AS_ROOT, reason="needs root to drop privileges; an unprivileged run executes these cases directly"
)

# The library runs the utility only from a trusted location (ruling R13), and a developer checkout
# may sit below a group-writable directory. So, as on a host, the cases source the library from a
# control plane: a private copy of lib/lifecycle.sh, the utility and the trust material.
PLANE: list[Path] = []


@pytest.fixture(scope="session", autouse=True)
def control_plane() -> Iterator[Path]:
    """A control plane under a fresh private temporary directory, the way setup.sh lays one out."""
    plane = Path(tempfile.mkdtemp(prefix="cb-lifecycle-plane-"))
    os.chmod(plane, 0o755)
    for source, perm in ((LIB, 0o644), (UTILITY, 0o755), (ROOT / "deploy" / "lib" / "bundle-signature.sh", 0o644)):
        shutil.copyfile(source, plane / source.name)
        os.chmod(plane / source.name, perm)
    PLANE.append(plane)
    yield plane
    PLANE.remove(plane)
    shutil.rmtree(plane)


def _system_python() -> str:
    """The host's root-owned python3: /usr/bin/python3 where it exists (the library's default), else the image's."""
    for candidate in ("/usr/bin/python3", "/usr/local/bin/python3"):
        path = Path(candidate)
        if path.exists() and path.resolve().stat().st_uid == 0 and path.lstat().st_uid == 0:
            return candidate
    pytest.fail("no root-owned python3 in /usr/bin or /usr/local/bin: the library refuses every other interpreter")


SYSTEM_PYTHON = _system_python()


STRICT = "set -Eeuo pipefail\ntrap 'echo \"ERR-TRAP: $BASH_COMMAND\" >&2' ERR\n"


def prelude(library: Path | None = None, plane: Path | None = None) -> str:
    """errexit and an ERR trap, as install.sh runs, with a library sourced (the control plane's by default).

    `plane` points the library's control-plane fallback somewhere else than its real fixed path.
    """
    return (
        STRICT
        + f'source "{library or PLANE[-1] / "lifecycle.sh"}"\n'
        + f'CB_LIFECYCLE_SYSTEM_PYTHON="{SYSTEM_PYTHON}"\n'
        + (f'CB_LIFECYCLE_CONTROL_PLANE="{plane}"\n' if plane is not None else "")
    )


ACQUIRE = 'cb_lifecycle_lock_acquire "cb update" || exit $?\n'
LEGACY = "cb_lifecycle_begin kind=legacy action=update adapter=native source_version=0.4.6 target_version=0.4.7 || exit $?\n"
PLAN_DIGEST = "sha256:" + "a" * 64
MANIFEST = "sha256:" + "e" * 64
TRANSACTION = (
    f"cb_lifecycle_begin kind=transaction action=update adapter=native plan_digest={PLAN_DIGEST} "
    "source_version=0.4.6 target_version=0.4.7 target_artifact_digest=sha256:" + "c" * 64 + " || exit $?\n"
)


def env_for(state: Path | None, extra: dict[str, str] | None = None) -> dict[str, str]:
    """The test's environment without inherited lifecycle variables, plus the seam."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CB_LIFECYCLE_", "_CB_LIFECYCLE_"))}
    if state is not None:
        env["CB_LIFECYCLE_ROOT"] = str(state)
    env.update(extra or {})
    return env


def sh(script: str, state: Path | None, extra: dict[str, str] | None = None,
       preexec: Callable[[], None] | None = None, head: str | None = None) -> subprocess.CompletedProcess[str]:
    """One bash process with the library sourced, under errexit and an ERR trap like install.sh.

    `head` replaces the default prelude (another library, another control plane).
    """
    return subprocess.run(
        ["bash", "-c", (prelude() if head is None else head) + script], capture_output=True, text=True,
        env=env_for(state, extra), timeout=60, check=False, preexec_fn=preexec,
    )


def ok(result: subprocess.CompletedProcess[str]) -> subprocess.CompletedProcess[str]:
    """Assert success and that nothing tripped the ERR trap."""
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ERR-TRAP" not in result.stderr, result.stderr
    return result


def operations(state: Path) -> Path:
    return state / "private" / "operations"


def journal_of(state: Path, op: str) -> dict[str, Any]:
    data = (operations(state) / op / "journal.json").read_bytes()
    parsed: dict[str, Any] = LS.parse_document("journal", data)
    return parsed


def index_of(state: Path) -> dict[str, Any]:
    parsed: dict[str, Any] = LS.parse_document("history", (state / "history.json").read_bytes())
    return parsed


def mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


def make_state(state: Path) -> Path:
    """Create the tree through the library and release it; returns the lock path."""
    ok(sh(ACQUIRE + "cb_lifecycle_lock_release\n", state))
    return state / "private" / "lock"


def op_from(result: subprocess.CompletedProcess[str]) -> str:
    match = re.search(r"^op=(op-[0-9]{8}-[0-9]{3,9})$", result.stdout, re.MULTILINE)
    assert match, result.stdout + result.stderr
    return match.group(1)


def utility(request: dict[str, Any], state: Path, extra: dict[str, str] | None = None,
            pass_fds: tuple[int, ...] = (), preexec: Callable[[], None] | None = None,
            ) -> subprocess.CompletedProcess[str]:
    """Run the utility directly, the way lifecycle.sh does."""
    return subprocess.run(
        [sys.executable, "-I", str(UTILITY)], input=json.dumps(request), capture_output=True, text=True,
        env=env_for(state, extra), timeout=60, check=False, pass_fds=pass_fds, preexec_fn=preexec,
    )


def ack(text: str) -> dict[str, list[str]]:
    lines: dict[str, list[str]] = {}
    for line in text.splitlines():
        key, _, value = line.partition("=")
        lines.setdefault(key, []).append(value)
    return lines


def tree_snapshot(state: Path) -> dict[str, bytes]:
    return {str(p.relative_to(state)): p.read_bytes() for p in sorted(state.rglob("*")) if p.is_file()}


@seam
def test_a_legacy_operation_is_journaled_durably_with_private_modes(tmp_path: Path) -> None:
    state = tmp_path / "state"
    r = ok(sh(ACQUIRE + LEGACY + 'echo "op=$CB_LIFECYCLE_OPERATION"\n'
              "cb_lifecycle_checkpoint state=committed outcome=committed || exit $?\n"
              "cb_lifecycle_lock_release\n", state))
    op = op_from(r)
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    assert re.fullmatch(rf"op-{today}-[0-9]{{3}}", op)
    journal = journal_of(state, op)
    assert [c["state"] for c in journal["checkpoints"]] == ["applying", "committed"]
    assert journal["generation"] == 2
    assert journal["source"] == {"version": "0.4.6", "artifact_digest": None}
    assert journal["plan_digest"] is None and journal["kind"] == "legacy"
    assert [c["sequence"] for c in journal["checkpoints"]] == [1, 2]
    assert mode(operations(state)) == 0o700
    assert mode(operations(state) / op) == 0o700
    assert mode(operations(state) / op / "journal.json") == 0o600
    assert mode(operations(state) / op / "sequence") == 0o600
    assert (operations(state) / op / "sequence").read_text() == "2\n"
    assert mode(state / "history.json") == 0o644
    entry = index_of(state)["operations"][0]
    assert entry["operation_id"] == op and entry["outcome"] == "committed"
    assert entry["source_version"] == "0.4.6" and entry["target_version"] == "0.4.7"
    leftovers = [p.name for p in state.rglob(".*")]
    assert leftovers == [], leftovers
    assert r.stdout.strip() == f"op={op}", "the library prints nothing of its own on stdout"


@seam
def test_a_permissive_umask_never_loosens_private_modes(tmp_path: Path) -> None:
    state = tmp_path / "state"
    make_state(state)
    op = op_from(ok(sh("umask 0000\n" + ACQUIRE + LEGACY + 'echo "op=$CB_LIFECYCLE_OPERATION"\n', state)))
    assert (mode(operations(state)), mode(operations(state) / op)) == (0o700, 0o700)
    assert mode(operations(state) / op / "journal.json") == 0o600
    assert mode(state / "history.json") == 0o644


@seam
def test_a_legacy_version_that_is_not_an_installed_version_is_recorded_as_null(tmp_path: Path) -> None:
    state = tmp_path / "state"
    r = ok(sh(ACQUIRE + "cb_lifecycle_begin kind=legacy action=update adapter=mono "
              "\"source_version=$(printf 'v\\001')\" target_version=latest || exit $?\n"
              'echo "op=$CB_LIFECYCLE_OPERATION"\n', state))
    journal = journal_of(state, op_from(r))
    assert journal["source"] is None
    assert journal["target"] == {"version": "latest", "artifact_digest": None}
    r = sh(ACQUIRE + TRANSACTION.replace("source_version=0.4.6", "\"source_version=$(printf 'v\\001')\""), state)
    assert r.returncode == 2 and "not an installed version" in r.stderr, r.stderr


@seam
def test_a_signal_never_cuts_a_request_in_half(tmp_path: Path) -> None:
    proc = subprocess.Popen([sys.executable, "-I", str(UTILITY)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=env_for(tmp_path / "absent"))
    try:
        assert proc.stdin is not None
        proc.stdin.write(b'{"request":')
        proc.stdin.flush()
        time.sleep(0.5)  # it is reading the request now
        for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            proc.send_signal(number)
        out, err = proc.communicate(b'"inspect","operation_id":"op-20261001-001"}', timeout=60)
        assert out == b""
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    assert proc.returncode == 2, err
    assert b"no operation op-20261001-001 exists" in err


@seam
def test_a_transaction_walks_its_states_and_the_coordinator_accepts_what_was_written(tmp_path: Path) -> None:
    state = tmp_path / "state"
    r = ok(sh(
        ACQUIRE + TRANSACTION + 'echo "op=$CB_LIFECYCLE_OPERATION"\n'
        "cb_lifecycle_checkpoint state=staged\n"
        "cb_lifecycle_checkpoint state=verified evidence_check=signature evidence_result=passed "
        "'evidence_detail=key 0123456789abcdef'\n"
        f"cb_lifecycle_checkpoint state=recovery_saved recovery_operation_id=$CB_LIFECYCLE_OPERATION "
        f"recovery_manifest_digest={MANIFEST}\n"
        "cb_lifecycle_checkpoint state=applying\n"
        "cb_lifecycle_checkpoint state=applying step=units_stopped\n"
        "cb_lifecycle_checkpoint state=applying step=tree_swapped\n"
        "cb_lifecycle_checkpoint state=checking\n"
        "cb_lifecycle_checkpoint state=committed outcome=committed\n"
        "cb_lifecycle_lock_release\n", state))
    op = op_from(r)
    journal = journal_of(state, op)
    states = [(c["state"], c.get("step")) for c in journal["checkpoints"]]
    # J3: the later step replaced the earlier stepped record in place.
    assert states == [("planned", None), ("staged", None), ("verified", None), ("recovery_saved", None),
                      ("applying", None), ("applying", "tree_swapped"), ("checking", None), ("committed", None)]
    assert journal["generation"] == 9
    sequences = [c["sequence"] for c in journal["checkpoints"]]
    assert sequences == sorted(sequences) and sequences[5] == 7, "the replaced step drew a new sequence"
    assert journal["recovery"] == {"operation_id": op, "manifest_digest": MANIFEST}
    assert journal["evidence"] == [{"check": "signature", "result": "passed", "detail": "key 0123456789abcdef"}]
    node = shutil.which("node")
    if node is None:
        pytest.fail("node is required: the coordinator must accept every journal the native utility writes")
    script = (
        "import('./src/lifecycle-contract.js').then(({parseDocument}) => {"
        " const fs = require('node:fs');"
        " parseDocument('journal', fs.readFileSync(process.argv[1]));"
        " parseDocument('history', fs.readFileSync(process.argv[2]));"
        " console.log('accepted'); })"
    )
    checked = subprocess.run(
        [node, "-e", script, str(operations(state) / op / "journal.json"), str(state / "history.json")],
        cwd=ROOT / "packages" / "cli", capture_output=True, text=True, timeout=60, check=False,
    )
    assert checked.stdout.strip() == "accepted", checked.stderr


@seam
def test_checkpoint_events_reach_only_the_event_descriptor_and_only_after_the_write(tmp_path: Path) -> None:
    state = tmp_path / "state"
    events = tmp_path / "events.jsonl"
    r = ok(sh(
        f'exec {{ev}}>"{events}"\nexport CB_LIFECYCLE_EVENT_FD=$ev\n'
        + ACQUIRE + LEGACY + 'echo "op=$CB_LIFECYCLE_OPERATION"\n'
        "if cb_lifecycle_checkpoint state=verified; then echo accepted; else echo \"refused $?\"; fi\n"
        "cb_lifecycle_checkpoint state=committed outcome=committed\n"
        "cb_lifecycle_lock_release\n", state))
    op = op_from(r)
    assert "refused 2" in r.stdout, "legacy applying -> verified is not a transition"
    lines = events.read_text().splitlines()
    parsed = [LS.parse_document("event", line.encode()) for line in lines]
    assert [(e["type"], e["source"], e["state"], e["generation"]) for e in parsed] == [
        ("checkpoint", "native", "applying", 1), ("checkpoint", "native", "committed", 2)]
    assert [e["operation_id"] for e in parsed] == [op, op]
    assert parsed[0]["sequence"] < parsed[1]["sequence"]
    journal = journal_of(state, op)
    assert [c["sequence"] for c in journal["checkpoints"]] == [e["sequence"] for e in parsed]
    assert "{" not in r.stdout and "{" not in r.stderr, "no event leaks onto stdout or stderr"


@seam
def test_a_closed_event_descriptor_never_fails_a_durable_checkpoint(tmp_path: Path) -> None:
    state = tmp_path / "state"
    r = ok(sh(
        "exec {ev}> >(exit 0)\nexport CB_LIFECYCLE_EVENT_FD=$ev\nsleep 0.2\n"
        + ACQUIRE + LEGACY + 'echo "op=$CB_LIFECYCLE_OPERATION"\n'
        "cb_lifecycle_checkpoint state=committed outcome=committed\necho done\n", state))
    assert "done" in r.stdout
    assert journal_of(state, op_from(r))["generation"] == 2


@seam
def test_progress_events_share_the_operations_sequence_and_never_touch_its_records(tmp_path: Path) -> None:
    """Ruling R15: cb_lifecycle_emit draws from the operation's counter under the lock, after its checkpoints."""
    state = tmp_path / "state"
    events = tmp_path / "events.jsonl"
    saved = tmp_path / "saved"
    saved.mkdir()
    r = ok(sh(
        f'exec {{ev}}>"{events}"\nexport CB_LIFECYCLE_EVENT_FD=$ev\n'
        + ACQUIRE + LEGACY + 'op="$CB_LIFECYCLE_OPERATION"\necho "op=$op"\n'
        f'cp "$CB_LIFECYCLE_ROOT/history.json" "$CB_LIFECYCLE_ROOT/private/operations/$op/journal.json" "{saved}/"\n'
        "cb_lifecycle_emit type=phase phase=apply status=started\n"
        "cb_lifecycle_emit type=progress phase=apply done=1 total=3 unit=steps\n"
        "cb_lifecycle_emit type=progress phase=download done=4096 unit=bytes\n"
        "cb_lifecycle_emit type=phase phase=apply status=completed duration_ms=1250\n"
        'cb_lifecycle_emit type=diagnostic level=warning code=PREFLIGHT "message=$HOSTILE"\n'
        f'cmp "$CB_LIFECYCLE_ROOT/history.json" "{saved}/history.json"\n'
        f'cmp "$CB_LIFECYCLE_ROOT/private/operations/$op/journal.json" "{saved}/journal.json"\n'
        "cb_lifecycle_checkpoint state=committed outcome=committed\n"
        "cb_lifecycle_lock_release\n", state, {"HOSTILE": "token=hunter2 \x1b[31mred\x1b[0m\nnext line"}))
    op = op_from(r)
    parsed = [LS.parse_document("event", line.encode()) for line in events.read_text().splitlines()]
    assert [(e["type"], e["sequence"]) for e in parsed] == [
        ("checkpoint", 1), ("phase", 2), ("progress", 3), ("progress", 4), ("phase", 5), ("diagnostic", 6), ("checkpoint", 7)]
    assert all(e["source"] == "native" and e["operation_id"] == op for e in parsed)
    assert (parsed[2]["done"], parsed[2]["total"], parsed[2]["unit"]) == (1, 3, "steps")
    assert parsed[3]["total"] is None, "an unknown total is null, never guessed"
    assert parsed[4]["duration_ms"] == 1250
    assert parsed[5]["message"] == "token (redacted) \\u001b[31mred\\u001b[0m\nnext line"
    assert parsed[5]["code"] == "PREFLIGHT" and parsed[5]["level"] == "warning"
    journal = journal_of(state, op)
    assert [c["sequence"] for c in journal["checkpoints"]] == [1, 7] and journal["generation"] == 2
    assert (operations(state) / op / "sequence").read_text() == "7\n"
    assert mode(operations(state) / op / "sequence") == 0o600
    assert "hunter2" not in events.read_text() + r.stdout + r.stderr
    assert "{" not in r.stdout and "{" not in r.stderr, "no event leaks onto stdout or stderr"


@seam
def test_without_an_event_descriptor_emit_writes_nothing(tmp_path: Path) -> None:
    state = tmp_path / "state"
    r = ok(sh(ACQUIRE + LEGACY + 'echo "op=$CB_LIFECYCLE_OPERATION"\n'
              "cb_lifecycle_emit type=phase phase=apply status=started\n"
              "CB_LIFECYCLE_EVENT_FD=1 cb_lifecycle_emit type=phase phase=apply status=completed\n"
              "cb_lifecycle_checkpoint state=committed outcome=committed\n", state))
    op = op_from(r)
    assert [c["sequence"] for c in journal_of(state, op)["checkpoints"]] == [1, 2], "no sequence was spent"
    assert "{" not in r.stdout + r.stderr


@seam
@pytest.mark.parametrize("members, problem", [
    (["type=checkpoint", "state=committed", "generation=2"], "type is not a valid event type"),
    (["type=progress", "phase=apply", "done=4", "total=3", "unit=steps"], "done exceeds total"),
    (["type=progress", "phase=apply", "done=1", "unit=steps", "status=started"], "status is not a member of a progress event"),
    (["type=phase", "phase=apply"], "a phase event needs status"),
    (["type=phase", "phase=warp", "status=started"], "phase is not a valid phase"),
    (["type=phase", "phase=apply", "status=started", "duration_ms=5"], "a duration belongs to a completed or failed phase"),
    (["type=diagnostic", "level=info", "message=x", "password=hunter2"], "password looks like a secret field"),
], ids=["checkpoint", "done over total", "foreign member", "missing member", "unknown phase", "early duration",
        "secret field"])
def test_a_malformed_event_is_refused_with_2_and_spends_no_sequence(members: list[str], problem: str, tmp_path: Path) -> None:
    state = tmp_path / "state"
    events = tmp_path / "events.jsonl"
    r = ok(sh(
        f'exec {{ev}}>"{events}"\nexport CB_LIFECYCLE_EVENT_FD=$ev\n'
        + ACQUIRE + LEGACY + 'echo "op=$CB_LIFECYCLE_OPERATION"\n'
        f"if cb_lifecycle_emit {' '.join(members)}; then echo accepted; else echo \"refused $?\"; fi\n", state))
    assert "refused 2" in r.stdout, r.stdout + r.stderr
    assert problem in r.stderr, r.stderr
    assert len(events.read_text().splitlines()) == 1, "only the begin checkpoint was emitted"
    assert (operations(state) / op_from(r) / "sequence").read_text() == "1\n"


@seam
def test_an_event_needs_the_lock_bound_to_its_operation(tmp_path: Path) -> None:
    state = tmp_path / "state"
    r = ok(sh(ACQUIRE + LEGACY + 'echo "op=$CB_LIFECYCLE_OPERATION"\ncb_lifecycle_lock_release\n', state))
    op = op_from(r)
    emit = {"request": "emit", "operation_id": op, "type": "phase", "phase": "apply", "status": "started"}
    refused = utility(emit, state)
    assert refused.returncode == 2 and "lock" in refused.stderr, refused.stderr
    other = ok(sh(ACQUIRE + LEGACY + 'op="$CB_LIFECYCLE_OPERATION"\n'
                  f"if cb_lifecycle_state emit operation_id={op} type=phase phase=apply status=started; "
                  'then echo accepted; else echo "refused $?"; fi\n', state))
    assert "refused 2" in other.stdout and f"not {op}" in other.stderr
    durable = journal_of(state, op)["checkpoints"][-1]["sequence"]
    assert (operations(state) / op / "sequence").read_text() == f"{durable}\n", "no refused event spent a sequence"


def _emitted(events: Path, op: str) -> list[dict[str, Any]]:
    """Every line on the event descriptor, parsed, after checking the order a consumer requires (E3)."""
    parsed = [LS.parse_document("event", line.encode()) for line in events.read_text().splitlines()]
    sequences = [e["sequence"] for e in parsed]
    assert all(e["operation_id"] == op and e["source"] == "native" for e in parsed)
    assert sequences == sorted(set(sequences)), f"sequences must rise in the order they reach the descriptor: {sequences}"
    return parsed


@seam
def test_writers_sharing_the_lock_draw_distinct_sequences_and_write_them_in_order(tmp_path: Path) -> None:
    """Holders of one inherited lock (R9: a subshell, a handed-down child) emit at once; E3 still holds."""
    state = tmp_path / "state"
    events = tmp_path / "events.jsonl"
    r = ok(sh(
        f'exec {{ev}}>"{events}"\nexport CB_LIFECYCLE_EVENT_FD=$ev\n'
        + ACQUIRE + LEGACY + 'echo "op=$CB_LIFECYCLE_OPERATION"\n'
        "for i in 1 2 3 4 5 6 7 8; do ( cb_lifecycle_emit type=progress phase=apply done=$i total=8 unit=steps ) & done\n"
        "wait\ncb_lifecycle_lock_release\n", state))
    op = op_from(r)
    parsed = _emitted(events, op)
    assert [e["sequence"] for e in parsed] == list(range(1, 10)), "begin, then eight distinct progress events"
    assert sorted(e["done"] for e in parsed[1:]) == list(range(1, 9)), "no event was lost"
    assert (operations(state) / op / "sequence").read_text() == "9\n"
    assert "lifecycle state" not in r.stderr, r.stderr


@seam
def test_events_racing_checkpoints_never_lose_a_checkpoint_event_or_a_checkpoint(tmp_path: Path) -> None:
    """Two emit loops in background subshells race stepped checkpoints of the same operation.

    No sequence repeats, the descriptor carries them in rising order (a consumer would drop a
    checkpoint event that arrived after a later sequence), no writer removes another's temporary
    file, and every durable checkpoint is acknowledged.
    """
    state = tmp_path / "state"
    events = tmp_path / "events.jsonl"
    r = ok(sh(
        f'exec {{ev}}>"{events}"\nexport CB_LIFECYCLE_EVENT_FD=$ev\n'
        + ACQUIRE + LEGACY + 'echo "op=$CB_LIFECYCLE_OPERATION"\n'
        "for loop in 1 2; do\n"
        "  ( for i in $(seq 1 20); do cb_lifecycle_emit type=progress phase=apply done=$i unit=steps; done ) &\n"
        "done\n"
        "for i in $(seq 1 20); do cb_lifecycle_checkpoint state=applying step=s$i || exit $?; done\n"
        "wait\ncb_lifecycle_checkpoint state=committed outcome=committed\ncb_lifecycle_lock_release\n", state))
    op = op_from(r)
    parsed = _emitted(events, op)
    assert "cannot record" not in r.stderr and "lifecycle state" not in r.stderr, r.stderr
    assert sum(e["type"] == "progress" for e in parsed) == 40, "every emit reached the descriptor"
    checkpoints = [e for e in parsed if e["type"] == "checkpoint"]
    assert [e["generation"] for e in checkpoints] == list(range(1, 23)), "every checkpoint event, in order"
    journal = journal_of(state, op)
    assert journal["generation"] == 22
    assert [c["sequence"] for c in journal["checkpoints"]] == [checkpoints[0]["sequence"], *(e["sequence"] for e in checkpoints[-2:])]
    assert (operations(state) / op / "sequence").read_text() == f"{len(parsed)}\n"
    assert not [p.name for p in (operations(state) / op).iterdir() if p.name.startswith(".")], "no temporary file is left"


@seam
def test_the_clis_history_reads_what_the_utility_wrote_and_never_settles_a_killed_operation(
    tmp_path: Path, procs: list[subprocess.Popen[str]],
) -> None:
    """Contract section 8 and ruling T3-n, end to end: utility-written index, coordinator reader."""
    node = shutil.which("node")
    if node is None:
        pytest.fail("node is required: the CLI's history must read the index the native utility writes")
    state = tmp_path / "state"

    def history(*flags: str) -> subprocess.CompletedProcess[str]:
        script = "import('./src/main.js').then(async ({ run }) => { process.exitCode = await run(process.argv.slice(1)); })"
        return subprocess.run([node, "-e", script, "history", *flags], cwd=ROOT / "packages" / "cli", capture_output=True,
                              text=True, timeout=60, check=False, env=env_for(state))

    empty = history("--json")
    assert empty.returncode == 0 and json.loads(empty.stdout)["operations"] == [], empty.stderr
    ok(sh(ACQUIRE + LEGACY + "cb_lifecycle_checkpoint state=committed outcome=committed\n", state))
    holder = subprocess.Popen(
        ["bash", "-c", prelude() + ACQUIRE + LEGACY + 'echo "op=$CB_LIFECYCLE_OPERATION"\nread -r _ || true\n'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env_for(state))
    procs.append(holder)
    assert holder.stdout is not None
    killed = holder.stdout.readline().strip().removeprefix("op=")
    holder.send_signal(signal.SIGKILL)
    holder.wait(timeout=15)

    listed = history("--json")
    assert listed.returncode == 0, listed.stderr
    result = LS.parse_document("result", listed.stdout.rstrip("\n").encode())
    assert result["operations"] == index_of(state)["operations"], "--json passes the index through unchanged"
    shown = history()
    assert shown.returncode == 0 and shown.stderr == "", shown.stderr
    assert f"{killed}  update (legacy, native)\n  Status    in progress or interrupted (last recorded state: applying)\n" in shown.stdout
    assert "  Status    committed\n" in shown.stdout

    ok(sh(ACQUIRE + "cb_lifecycle_state list >/dev/null\n", state))
    settled = history()
    assert f"{killed}  update (legacy, native)\n  Status    interrupted after changes began (last checkpoint: applying)\n" in settled.stdout

    (state / "history.json").chmod(0o664)
    loose = history("--json")
    assert loose.returncode == 6 and json.loads(loose.stdout)["error"]["code"] == "PERMISSION"


@seam
def test_a_write_without_the_lock_is_refused_and_changes_nothing(tmp_path: Path, procs: list[subprocess.Popen[str]]) -> None:
    state = tmp_path / "state"
    lock = make_state(state)
    before = tree_snapshot(state)
    begin = {"request": "begin", "kind": "legacy", "action": "restore", "adapter": "native"}
    r = utility(begin, state)
    assert r.returncode == 2 and "lock" in r.stderr, r.stderr
    # A descriptor of the lock file that does not hold the lock proves nothing.
    fd = os.open(lock, os.O_RDONLY)
    try:
        r = utility(begin, state, {"CB_LIFECYCLE_LOCK_FD": str(fd)}, pass_fds=(fd,))
        assert r.returncode == 2, r.stderr
        holder = subprocess.Popen(["bash", "-c", prelude() + ACQUIRE + "echo ready\nread -r _ || true\n"],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env_for(state))
        procs.append(holder)
        assert holder.stdout is not None and holder.stdout.readline().strip() == "ready"
        r = utility(begin, state, {"CB_LIFECYCLE_LOCK_FD": str(fd)}, pass_fds=(fd,))
        assert r.returncode == 2, r.stderr
    finally:
        os.close(fd)
    after = tree_snapshot(state)
    after.pop("private/owner", None)
    before.pop("private/owner", None)
    assert after == before
    assert not operations(state).exists()


@pytest.fixture
def procs() -> Iterator[list[subprocess.Popen[str]]]:
    started: list[subprocess.Popen[str]] = []
    yield started
    for proc in started:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=15)
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            if stream is not None:
                stream.close()


@seam
def test_only_the_bound_operation_may_be_written(tmp_path: Path) -> None:
    state = tmp_path / "state"
    r = ok(sh(
        ACQUIRE + LEGACY + 'op="$CB_LIFECYCLE_OPERATION"\necho "op=$op"\n'
        'other="${op%-*}-999"\n'
        "if cb_lifecycle_state checkpoint operation_id=$other expected_generation=1 state=committed outcome=committed; "
        'then echo "other accepted"; else echo "other refused $?"; fi\n'
        'if CB_LIFECYCLE_OPERATION=$other cb_lifecycle_state checkpoint operation_id=$other expected_generation=1 '
        'state=committed outcome=committed; then echo "rebound accepted"; else echo "rebound refused $?"; fi\n', state))
    assert "other refused 2" in r.stdout
    assert "rebound refused 2" in r.stdout
    assert journal_of(state, op_from(r))["generation"] == 1


@seam
def test_an_invalid_transition_is_refused_and_the_journal_is_unchanged(tmp_path: Path) -> None:
    state = tmp_path / "state"
    r = ok(sh(ACQUIRE + LEGACY + 'echo "op=$CB_LIFECYCLE_OPERATION"\n'
              "cb_lifecycle_checkpoint state=committed outcome=committed\n"
              'if cb_lifecycle_checkpoint state=recovering; then echo accepted; else echo "refused $?"; fi\n', state))
    assert "refused 2" in r.stdout
    assert "nothing may follow" in r.stderr
    assert journal_of(state, op_from(r))["generation"] == 2


@seam
def test_a_stale_writer_is_refused_and_the_next_mutation_never_runs(tmp_path: Path) -> None:
    state = tmp_path / "state"
    marker = tmp_path / "mutated"
    r = sh(ACQUIRE + LEGACY + 'echo "op=$CB_LIFECYCLE_OPERATION"\n'
           "cb_lifecycle_checkpoint state=applying step=units_stopped\n"
           # A writer that still believes the operation is at generation 1 has missed that step.
           'cb_lifecycle_state checkpoint operation_id="$CB_LIFECYCLE_OPERATION" expected_generation=1 '
           "state=committed outcome=committed || exit $?\n"
           'touch "$MUTATION"\n', state, {"MUTATION": str(marker)})
    assert r.returncode == 9, r.stderr
    assert "stale" in r.stderr
    assert not marker.exists()
    journal = journal_of(state, op_from(r))
    assert journal["generation"] == 2 and journal["checkpoints"][-1]["state"] == "applying"


CHILD_CHECKPOINT = """\
set -Eeuo pipefail
source "$CB_TEST_LIBRARY"
CB_LIFECYCLE_SYSTEM_PYTHON="$CB_TEST_PYTHON"
cb_lifecycle_lock_acquire "restore" || exit $?
cb_lifecycle_checkpoint state=applying step=data_restored || exit $?
cb_lifecycle_lock_release
"""


@seam
@pytest.mark.parametrize("closing", ["committed", "recovery_required"])
def test_the_parent_checkpoints_after_a_child_and_a_subshell_it_handed_the_lock_to(
    closing: str, tmp_path: Path,
) -> None:
    # cb update -> restore.sh: the child joins through the handoff and records its step, then
    # the parent records a step in a pipeline (a subshell) and closes the operation.
    state = tmp_path / "state"
    close = ("state=committed outcome=committed" if closing == "committed" else
             "state=recovery_required cause=apply_failed error_code=MANUAL 'error_reason=the new tree did not start'")
    r = ok(sh(ACQUIRE + LEGACY + 'echo "op=$CB_LIFECYCLE_OPERATION"\n'
              'bash -c "$CB_TEST_CHILD"\n'
              "cb_lifecycle_checkpoint state=applying step=units_started | cat\n"
              f"cb_lifecycle_checkpoint {close} || exit $?\n", state,
              {"CB_TEST_CHILD": CHILD_CHECKPOINT, "CB_TEST_LIBRARY": str(PLANE[-1] / "lifecycle.sh"),
               "CB_TEST_PYTHON": SYSTEM_PYTHON}))
    journal = journal_of(state, op_from(r))
    assert journal["generation"] == 4
    assert [(c["state"], c.get("step")) for c in journal["checkpoints"]] == [
        ("applying", None), ("applying", "units_started"), (closing, None)]
    if closing == "recovery_required":
        record = journal["checkpoints"][-1]
        assert record["cause"] == "apply_failed" and record["error"]["reason"] == "the new tree did not start"


FLAKY_PYTHON = """\
#!/bin/sh
# The trusted interpreter, except that one checkpoint request loses its acknowledgement:
# with CB_TEST_LANDS=1 the record is written first (the rename landed, its fsync failed),
# otherwise nothing is written. Either way the caller sees 7.
if [ "${{2:-}}" = "-B" ] && [ -e "$CB_TEST_FAULT" ]; then
  request=$(cat)
  case "$request" in
    *'"request":"checkpoint"'*)
      rm -f "$CB_TEST_FAULT"
      if [ "$CB_TEST_LANDS" = 1 ]; then printf '%s' "$request" | {python} "$@" >/dev/null; fi
      exit 7 ;;
  esac
  printf '%s' "$request" | {python} "$@"
  exit $?
fi
exec {python} "$@"
"""


@seam
@pytest.mark.parametrize("lands", [True, False], ids=["the record landed", "nothing was written"])
def test_after_an_unacknowledged_checkpoint_the_next_is_stale_only_if_the_record_may_be_its_own(
    lands: bool, tmp_path: Path,
) -> None:
    state = tmp_path / "state"
    marker = tmp_path / "mutated"
    flaky = tmp_path / "bundle" / "python" / "bin" / "python3"
    flaky.parent.mkdir(parents=True)
    flaky.write_text(FLAKY_PYTHON.format(python=SYSTEM_PYTHON))
    os.chmod(flaky, 0o755)
    fault = tmp_path / "fault"
    r = sh(f'CB_LIFECYCLE_SYSTEM_PYTHON="{tmp_path}/no-python3"\ncb_lifecycle_python "{flaky}" || exit $?\n'
           + ACQUIRE + LEGACY + 'echo "op=$CB_LIFECYCLE_OPERATION"\ntouch "$CB_TEST_FAULT"\n'
           'if cb_lifecycle_checkpoint state=applying step=units_stopped; then echo "first ok"; else echo "first $?"; fi\n'
           "cb_lifecycle_checkpoint state=recovery_required cause=apply_failed error_code=MANUAL "
           "'error_reason=the units did not stop' || exit $?\n"
           'touch "$MUTATION"\n', state,
           {"CB_TEST_FAULT": str(fault), "CB_TEST_LANDS": "1" if lands else "0", "MUTATION": str(marker)})
    assert "first 7" in r.stdout, r.stdout + r.stderr
    journal = journal_of(state, op_from(r))
    if lands:
        # This shell cannot tell its own unacknowledged record from another writer's: stale.
        assert r.returncode == 9, r.stderr
        assert "not acknowledged" in r.stderr
        assert not marker.exists()
        assert journal["generation"] == 2 and journal["checkpoints"][-1].get("step") == "units_stopped"
    else:
        assert r.returncode == 0, r.stderr
        assert marker.exists()
        assert journal["generation"] == 2 and journal["checkpoints"][-1]["state"] == "recovery_required"


@seam
def test_a_full_disk_fails_the_checkpoint_and_blocks_the_next_mutation(tmp_path: Path) -> None:
    state = tmp_path / "state"
    marker = tmp_path / "mutated"
    r = ok(sh(ACQUIRE + LEGACY + 'echo "op=$CB_LIFECYCLE_OPERATION"\n', state))
    op = op_from(r)
    before = (operations(state) / op / "journal.json").read_bytes()

    def small_disk() -> None:
        # A write past this size fails with EFBIG, as a full disk fails one with ENOSPC.
        signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
        resource.setrlimit(resource.RLIMIT_FSIZE, (len(before) - 8, len(before) - 8))

    r = sh(ACQUIRE + f"cb_lifecycle_lock_bind_operation {op}\n"
           "cb_lifecycle_checkpoint state=recovery_required cause=apply_failed error_code=MANUAL "
           "'error_reason=the new tree did not start' || exit $?\n"
           'touch "$MUTATION"\n', state, {"MUTATION": str(marker)}, preexec=small_disk)
    assert r.returncode == 7, r.stderr
    assert "disk is full" in r.stderr
    assert not marker.exists()
    assert (operations(state) / op / "journal.json").read_bytes() == before
    assert [p.name for p in state.rglob(".*")] == []


@seam
def test_a_full_disk_at_begin_leaves_no_operation_behind(tmp_path: Path) -> None:
    state = tmp_path / "state"
    marker = tmp_path / "mutated"
    make_state(state)

    def small_disk() -> None:
        signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
        resource.setrlimit(resource.RLIMIT_FSIZE, (300, 300))

    r = sh(ACQUIRE + LEGACY + 'touch "$MUTATION"\n', state, {"MUTATION": str(marker)}, preexec=small_disk)
    assert r.returncode == 7, r.stderr
    assert not marker.exists()
    assert list(operations(state).iterdir()) == []


@seam
def test_an_unfinished_transaction_blocks_every_begin(tmp_path: Path) -> None:
    state = tmp_path / "state"
    r = ok(sh(ACQUIRE + TRANSACTION + 'echo "op=$CB_LIFECYCLE_OPERATION"\n'
              "cb_lifecycle_checkpoint state=staged\ncb_lifecycle_checkpoint state=verified\n"
              f"cb_lifecycle_checkpoint state=recovery_saved recovery_operation_id=$CB_LIFECYCLE_OPERATION "
              f"recovery_manifest_digest={MANIFEST}\n"
              "cb_lifecycle_checkpoint state=applying\n", state))
    first = op_from(r)
    marker = tmp_path / "mutated"
    r = sh(ACQUIRE + LEGACY + 'touch "$MUTATION"\n', state, {"MUTATION": str(marker)})
    assert r.returncode == 9, r.stderr
    assert first in r.stderr
    assert not marker.exists()
    record = journal_of(state, first)["checkpoints"][-1]
    # The next lock holder persisted what the gone process could not.
    assert {k: record.get(k) for k in ("state", "cause", "checkpoint", "outcome")} == {
        "state": "interrupted", "cause": "abandoned", "checkpoint": "applying", "outcome": None}
    assert [p.name for p in operations(state).iterdir()] == [first]
    entry = index_of(state)["operations"][0]
    assert (entry["operation_id"], entry["state"], entry["checkpoint"], entry["outcome"]) == (
        first, "interrupted", "applying", None)


@seam
def test_an_unfinished_legacy_record_is_named_but_does_not_block(tmp_path: Path) -> None:
    state = tmp_path / "state"
    first = op_from(ok(sh(ACQUIRE + LEGACY + 'echo "op=$CB_LIFECYCLE_OPERATION"\n', state)))
    r = ok(sh(ACQUIRE + LEGACY + 'echo "op=$CB_LIFECYCLE_OPERATION"\n', state))
    second = op_from(r)
    assert second != first and int(second.rsplit("-", 1)[1]) == int(first.rsplit("-", 1)[1]) + 1
    assert f"{first} (update) is unfinished" in r.stderr
    assert journal_of(state, first)["checkpoints"][-1]["cause"] == "abandoned"


@seam
def test_a_kill_before_mutation_closes_the_operation(tmp_path: Path, procs: list[subprocess.Popen[str]]) -> None:
    state = tmp_path / "state"
    holder = subprocess.Popen(
        ["bash", "-c", prelude() + ACQUIRE + TRANSACTION + "cb_lifecycle_checkpoint state=staged\n"
         'echo "op=$CB_LIFECYCLE_OPERATION"\nread -r _ || true\n'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env_for(state))
    procs.append(holder)
    assert holder.stdout is not None
    first = holder.stdout.readline().strip().removeprefix("op=")
    holder.send_signal(signal.SIGKILL)
    holder.wait(timeout=15)
    r = ok(sh(ACQUIRE + TRANSACTION, state))
    assert "unfinished" not in r.stderr
    record = journal_of(state, first)["checkpoints"][-1]
    assert {k: record.get(k) for k in ("state", "cause", "checkpoint", "outcome")} == {
        "state": "interrupted", "cause": "abandoned", "checkpoint": "staged", "outcome": "interrupted"}


@seam
def test_a_killed_apply_is_reported_interrupted_and_persisted_by_the_next_holder(
    tmp_path: Path, procs: list[subprocess.Popen[str]],
) -> None:
    state = tmp_path / "state"
    holder = subprocess.Popen(
        ["bash", "-c", prelude() + ACQUIRE + LEGACY + 'echo "op=$CB_LIFECYCLE_OPERATION"\n'
         # The operation the lock is bound to is running, so its own list leaves it alone.
         "cb_lifecycle_state list >/dev/null\necho listed\nread -r _ || true\n"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env_for(state))
    procs.append(holder)
    assert holder.stdout is not None
    op = holder.stdout.readline().strip().removeprefix("op=")
    assert holder.stdout.readline().strip() == "listed"
    assert journal_of(state, op)["checkpoints"][-1]["state"] == "applying"
    running = ack(utility({"request": "inspect", "operation_id": op}, state).stdout)
    assert running["status"] == ["running"]
    holder.send_signal(signal.SIGKILL)
    holder.wait(timeout=15)
    before = (operations(state) / op / "journal.json").read_bytes()
    r = utility({"request": "inspect", "operation_id": op}, state)
    assert r.returncode == 0, r.stderr
    seen = ack(r.stdout)
    assert seen["status"] == ["abandoned"] and seen["reported"] == ["interrupted"] and seen["state"] == ["applying"]
    assert (operations(state) / op / "journal.json").read_bytes() == before, "inspect writes nothing"
    # Until the next holder runs, the index still shows the last durable state, unsettled: no
    # outcome and a progress state (ruling T3-n). History presents that as in progress or
    # interrupted; it never shows it as settled.
    entry = index_of(state)["operations"][0]
    assert (entry["operation_id"], entry["state"], entry["outcome"], entry["checkpoint"]) == (op, "applying", None, None)
    listed = ack(ok(sh(ACQUIRE + "cb_lifecycle_state list\n", state)).stdout)
    assert listed["unfinished"] == [op]
    record = journal_of(state, op)["checkpoints"][-1]
    assert (record["state"], record["cause"], record["checkpoint"], "outcome" in record) == (
        "interrupted", "abandoned", "applying", False)
    entry = index_of(state)["operations"][0]
    assert (entry["operation_id"], entry["state"], entry["checkpoint"]) == (op, "interrupted", "applying")


def _write_raw_record(state: Path, name: str, data: bytes, dir_mode: int = 0o700, file_mode: int = 0o600) -> Path:
    directory = operations(state) / name
    directory.mkdir(mode=0o700, parents=False)
    os.chmod(directory, dir_mode)
    journal = directory / "journal.json"
    journal.write_bytes(data)
    os.chmod(journal, file_mode)
    return journal


@seam
def test_a_corrupt_record_is_reported_never_rewritten_and_blocks_only_a_transaction(tmp_path: Path) -> None:
    state = tmp_path / "state"
    make_state(state)
    operations(state).mkdir(mode=0o700)
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    corrupt = _write_raw_record(state, f"op-{today}-041", b'{"schema_version":1,"operation_id":')
    original = corrupt.read_bytes()
    listed = ack(ok(sh(ACQUIRE + "cb_lifecycle_state list\n", state)).stdout)
    assert listed["inspection"] == [f"op-{today}-041"]
    assert listed["retention"] == ["blocked"]
    entry = index_of(state)["operations"][0]
    assert entry["inspection_required"] is True and entry["record"] == f"op-{today}-041"
    assert "not valid JSON" in entry["reason"]
    r = sh(ACQUIRE + TRANSACTION, state)
    assert r.returncode == 9, r.stderr
    r = ok(sh(ACQUIRE + LEGACY + 'echo "op=$CB_LIFECYCLE_OPERATION"\n', state))
    assert "requires inspection" in r.stderr
    assert op_from(r) == f"op-{today}-042", "a new ID is never one a record already holds"
    assert corrupt.read_bytes() == original


@seam
@pytest.mark.parametrize("case", ["unsupported version", "symlinked journal", "loose journal mode",
                                  "loose directory mode", "names another operation", "stray entry"])
def test_records_that_cannot_be_trusted_require_inspection(case: str, tmp_path: Path) -> None:
    state = tmp_path / "state"
    make_state(state)
    operations(state).mkdir(mode=0o700)
    good = json.loads(json.dumps(next(v["document"] for v in VALID["journal"] if v["name"] == "legacy restore")))
    name = good["operation_id"]
    data = json.dumps(good).encode()
    if case == "unsupported version":
        _write_raw_record(state, name, json.dumps(dict(good, schema_version=2)).encode())
    elif case == "symlinked journal":
        target = tmp_path / "elsewhere.json"
        target.write_bytes(data)
        os.chmod(target, 0o600)
        (operations(state) / name).mkdir(mode=0o700)
        (operations(state) / name / "journal.json").symlink_to(target)
    elif case == "loose journal mode":
        _write_raw_record(state, name, data, file_mode=0o644)
    elif case == "loose directory mode":
        _write_raw_record(state, name, data, dir_mode=0o755)
    elif case == "names another operation":
        _write_raw_record(state, "op-20260930-777", data)
        name = "op-20260930-777"
    else:
        (operations(state) / "notes.txt").write_text("x")
        name = "notes.txt"
    before = tree_snapshot(state)
    inspected = utility({"request": "inspect", "operation_id": name}, state) if name.startswith("op-") else None
    if inspected is not None:
        assert inspected.returncode == (3 if case == "unsupported version" else 9), inspected.stderr
        assert ack(inspected.stdout)["inspection_required"] == ["yes"]
    listed = ack(ok(sh(ACQUIRE + "cb_lifecycle_state list\n", state)).stdout)
    assert listed["inspection"] == [name]
    entry = index_of(state)["operations"][0]
    assert entry["inspection_required"] is True
    after = tree_snapshot(state)
    for key in ("private/owner", "history.json"):
        before.pop(key, None)
        after.pop(key, None)
    assert after == before, "a record that requires inspection is never deleted or rewritten"


@seam
def test_an_entry_whose_name_is_not_utf8_requires_inspection_and_breaks_no_write(tmp_path: Path) -> None:
    state = tmp_path / "state"
    make_state(state)
    operations(state).mkdir(mode=0o700)
    os.mkdir(os.fsencode(operations(state)) + b"/op-bad\xff", 0o700)
    shown = "op-bad\\xff"
    listed = ack(ok(sh(ACQUIRE + "cb_lifecycle_state list\n", state)).stdout)
    assert listed["inspection"] == [shown] and listed["retention"] == ["blocked"]
    entry = index_of(state)["operations"][0]
    assert entry["inspection_required"] is True and entry["record"] is None
    assert entry["reason"].startswith(shown + ":")
    r = ok(sh(ACQUIRE + LEGACY + 'echo "op=$CB_LIFECYCLE_OPERATION"\n' + COMMIT, state))
    assert f"{shown} requires inspection" in r.stderr
    op = op_from(r)
    assert journal_of(state, op)["checkpoints"][-1]["outcome"] == "committed"
    # The begin was acknowledged and bound, so no retry left another operation behind.
    assert sorted(os.listdir(os.fsencode(operations(state)))) == sorted([b"op-bad\xff", op.encode()])
    assert [e.get("operation_id") for e in index_of(state)["operations"]] == [None, op]


@seam
def test_an_index_that_cannot_be_built_never_fails_an_acknowledged_write(
    held: Held, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(_: Any) -> Any:
        raise LS.StateError("USAGE", "the index is not valid")

    monkeypatch.setattr(LS, "build_index", broken)
    code, lines, err = held.request(request="begin", kind="legacy", action="migrate", adapter="native")
    assert code == 0, err
    op = lines["operation_id"][0]
    assert any("history.json was not updated" in w for w in lines["warning"])
    held.bind(op)
    code, lines, err = held.request(request="checkpoint", operation_id=op, expected_generation=1,
                                    state="committed", outcome="committed")
    assert code == 0, err
    assert lines["generation"] == ["2"] and any("journals are intact" in w for w in lines["warning"])
    assert journal_of(held.state, op)["checkpoints"][-1]["outcome"] == "committed"


@seam
def test_an_unsafe_tree_is_refused_with_6(tmp_path: Path) -> None:
    state = tmp_path / "state"
    make_state(state)
    os.chmod(state, 0o775)
    r = utility({"request": "inspect", "operation_id": "op-20261001-001"}, state)
    assert r.returncode == 6, r.stderr
    assert "writable by group or others" in r.stderr


def _finished_legacy(op: str, at: str, recovery: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "schema_version": 1, "operation_id": op, "kind": "legacy", "action": "restore", "adapter": "native",
        "generation": 2, "plan_digest": None, "identity_digest": None, "source": None, "target": None,
        "recovery": recovery, "evidence": [], "started_at": at, "updated_at": at,
        "checkpoints": [{"sequence": 1, "state": "applying", "at": at},
                        {"sequence": 2, "state": "committed", "at": at, "outcome": "committed"}],
    }


@seam
def test_the_index_keeps_unfinished_and_doubtful_records_when_it_overflows(tmp_path: Path) -> None:
    state = tmp_path / "state"
    make_state(state)
    operations(state).mkdir(mode=0o700)
    for n in range(1, 106):
        doc = _finished_legacy(f"op-20250101-{n:03d}", f"2025-01-01T00:{n // 60:02d}:{n % 60:02d}Z")
        _write_raw_record(state, doc["operation_id"], json.dumps(doc).encode())
    unfinished = _finished_legacy("op-20240101-001", "2024-01-01T00:00:00Z")
    unfinished["checkpoints"][1] = {"sequence": 2, "state": "recovery_required", "at": "2024-01-01T00:00:00Z",
                                    "cause": "apply_failed", "error": {"code": "MANUAL", "reason": "x"}}
    _write_raw_record(state, "op-20240101-001", json.dumps(unfinished).encode())
    _write_raw_record(state, "op-20240101-002", b"garbage")
    listed = ack(ok(sh(ACQUIRE + "cb_lifecycle_state list\n", state)).stdout)
    assert listed["operations"] == ["107"] and listed["indexed"] == ["100"] and listed["omitted"] == ["7"]
    entries = index_of(state)["operations"]
    assert len(entries) == 100
    assert entries[0]["operation_id"] == "op-20240101-001"
    assert entries[1]["inspection_required"] is True
    assert [e["operation_id"] for e in entries[2:4]] == ["op-20250101-105", "op-20250101-104"]


def _record(op: str, journal: dict[str, Any] | None) -> Any:
    return LS.Record(op, journal=journal, reason="" if journal else "is not valid JSON")


def test_retention_keeps_every_point_an_unfinished_operation_needs_and_the_last_success() -> None:
    def point(n: int) -> dict[str, str]:
        return {"operation_id": f"op-20260101-00{n}", "manifest_digest": "sha256:" + str(n) * 64}

    older = _finished_legacy("op-20260101-001", "2026-01-01T00:00:00Z", point(1))
    newest = _finished_legacy("op-20260101-002", "2026-01-02T00:00:00Z", point(2))
    superseded = _finished_legacy("op-20260101-003", "2026-01-01T12:00:00Z", point(3))
    # A rollback still running against the oldest point: releasing it would orphan the operation.
    rollback = _finished_legacy("op-20260101-004", "2026-01-03T00:00:00Z", point(1))
    rollback["checkpoints"] = rollback["checkpoints"][:1]
    records = [_record(j["operation_id"], j) for j in (older, newest, superseded, rollback)]
    protected, releasable, complete = LS.retention(records)
    ref = "{operation_id}:{manifest_digest}".format
    assert protected == sorted([ref(**point(1)), ref(**point(2))])
    assert releasable == [ref(**point(3))]
    assert complete
    protected, releasable, complete = LS.retention([*records, _record("op-20260101-005", None)])
    assert ref(**point(1)) in protected and releasable == [] and not complete


# --- Fault injection: every syscall of an atomic write, in process and as a real crash ---------

FAULT_POINTS = ("write", "fsync", "replace", "fsync_dir")


class Held:
    """This test process holding the host lock, bound to one operation, with the utility run in process."""

    def __init__(self, state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.state = state
        self.monkeypatch = monkeypatch
        self.fd = os.open(make_state(state), os.O_RDONLY)
        fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.set_inheritable(self.fd, True)
        monkeypatch.setenv("CB_LIFECYCLE_ROOT", str(state))
        monkeypatch.setenv("CB_LIFECYCLE_LOCK_FD", str(self.fd))
        self.bind("")

    def bind(self, op: str) -> None:
        """Write the owner record as lifecycle.sh's acquire and bind would."""
        owner = self.state / "private" / "owner"
        owner.write_text(f"pid={os.getpid()}\nstart=1\neuid={os.geteuid()}\nlabel=cb update\n"
                         f"since=2026-10-01T00:00:00Z\noperation={op}\n")
        os.chmod(owner, 0o600)
        self.monkeypatch.setenv("CB_LIFECYCLE_OPERATION", op)

    def request(self, **members: Any) -> tuple[int, dict[str, list[str]], str]:
        code, out, err = _run_inprocess(json.dumps(members).encode())
        return code, ack(out), err

    def close(self) -> None:
        os.close(self.fd)


@pytest.fixture
def held(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Held]:
    holder = Held(tmp_path / "state", monkeypatch)
    yield holder
    holder.close()


def _begin_bound(held: Held) -> str:
    code, lines, err = held.request(request="begin", kind="legacy", action="migrate", adapter="native")
    assert code == 0, err
    op = lines["operation_id"][0]
    held.bind(op)
    return op


@seam
def test_the_utility_writes_events_only_to_a_descriptor_it_accepts_and_only_after_the_write(
    held: Held, monkeypatch: pytest.MonkeyPatch,
) -> None:
    read_end, write_end = os.pipe()
    os.set_blocking(read_end, False)

    def drained() -> bytes:
        try:
            return os.read(read_end, 65536)
        except BlockingIOError:
            return b""

    try:
        monkeypatch.setenv("CB_LIFECYCLE_EVENT_FD", str(write_end))
        op = _begin_bound(held)
        first = drained().decode()
        assert first.endswith("\n") and LS.parse_document("event", first[:-1].encode())["state"] == "applying"

        real = LS.DISK.fsync_dir

        def full_disk(_fd: int) -> None:
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(LS.DISK, "fsync_dir", full_disk)
        code, _, _ = held.request(request="checkpoint", operation_id=op, expected_generation=1,
                                  state="committed", outcome="committed")
        monkeypatch.setattr(LS.DISK, "fsync_dir", real)
        assert code == 7 and drained() == b"", "a write that was not acknowledged emits nothing"

        counter = operations(held.state) / op / "sequence"
        before = int(counter.read_text())
        for refused in (str(held.fd), "2", "999", "03"):
            monkeypatch.setenv("CB_LIFECYCLE_EVENT_FD", refused)
            code, _, err = held.request(request="emit", operation_id=op, type="phase", phase="apply", status="started")
            assert code == 0, err
            assert drained() == b"", f"no event goes to descriptor {refused}"
        assert int(counter.read_text()) == before + 4, "each emit still spent its sequence; only the descriptor was refused"
    finally:
        os.close(read_end)
        os.close(write_end)


@seam
@pytest.mark.parametrize("point", FAULT_POINTS)
@pytest.mark.parametrize("nth", [1, 2], ids=["sequence file", "journal"])
def test_a_failed_write_leaves_the_old_or_the_new_record_and_never_acknowledges(
    point: str, nth: int, held: Held, monkeypatch: pytest.MonkeyPatch,
) -> None:
    op = _begin_bound(held)
    path = operations(held.state) / op / "journal.json"
    old = path.read_bytes()
    calls = {"n": 0}
    real = getattr(LS.DISK, point)

    def faulty(*args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == nth:
            raise OSError(28, "No space left on device")
        return real(*args, **kwargs)

    monkeypatch.setattr(LS.DISK, point, faulty)
    code, lines, err = held.request(request="checkpoint", operation_id=op, expected_generation=1,
                                    state="committed", outcome="committed")
    monkeypatch.setattr(LS.DISK, point, real)
    assert code == 7, err
    assert lines == {}, "nothing is acknowledged"
    assert "disk is full" in err
    now = path.read_bytes()
    landed = nth == 2 and point == "fsync_dir"  # the rename happened; only its durability is unknown
    assert now == old if not landed else LS.parse_document("journal", now)["generation"] == 2
    assert [p.name for p in held.state.rglob(".*")] == [], "temporaries are removed on failure"
    # The caller retries with the generation it last saw: fine if nothing landed, refused as stale if it did.
    code, _, err = held.request(request="checkpoint", operation_id=op, expected_generation=1,
                                state="committed", outcome="committed")
    assert code == (9 if landed else 0), err


CRASH_DRIVER = """
import importlib.util, io, json, os, sys
spec = importlib.util.spec_from_file_location("ls", sys.argv[1])
ls = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ls)
point, nth = sys.argv[2], int(sys.argv[3])
real = getattr(ls.DISK, point)
calls = [0]
def crash(*args, **kwargs):
    calls[0] += 1
    if calls[0] == nth:
        os._exit(137)  # what SIGKILL leaves: no cleanup, no unwinding
    return real(*args, **kwargs)
setattr(ls.DISK, point, crash)
sys.exit(ls.run(io.BytesIO(sys.argv[4].encode()), sys.stdout.write, sys.stderr.write))
"""


@seam
@pytest.mark.parametrize("point", FAULT_POINTS)
def test_a_crash_at_any_syscall_leaves_a_valid_record_and_the_next_writer_recovers(point: str, held: Held) -> None:
    op = _begin_bound(held)
    path = operations(held.state) / op / "journal.json"
    old = path.read_bytes()
    request = json.dumps({"request": "checkpoint", "operation_id": op, "expected_generation": 1,
                          "state": "committed", "outcome": "committed"})
    crashed = subprocess.run(
        [sys.executable, "-c", CRASH_DRIVER, str(UTILITY), point, "2", request],
        capture_output=True, text=True, env=dict(os.environ), timeout=60, check=False, pass_fds=(held.fd,),
    )
    assert crashed.returncode == 137, crashed.stderr
    assert crashed.stdout == "", "a crashed write acknowledged nothing"
    journal = LS.parse_document("journal", path.read_bytes())
    landed = point == "fsync_dir"
    assert (journal["generation"] == 2) if landed else (path.read_bytes() == old)
    # Readers skip a crashed writer's temporary; the next writer under the lock removes it.
    code, lines, err = held.request(request="list")
    assert code == 0 and lines["operations"] == ["1"], err
    code, _, err = held.request(request="checkpoint", operation_id=op, expected_generation=journal["generation"],
                                state="recovery_required", cause="apply_failed", error_code="MANUAL",
                                error_reason="stopped") if landed else held.request(
        request="checkpoint", operation_id=op, expected_generation=1, state="committed", outcome="committed")
    assert code == (2 if landed else 0), err  # a committed record closes the operation; nothing may follow it
    if not landed:
        assert [p.name for p in (operations(held.state) / op).iterdir() if p.name.startswith(".")] == []


# --- The shell never evaluates what a journal holds ----------------------------------------


@seam
def test_journal_text_is_never_executed_by_the_shell(tmp_path: Path) -> None:
    state = tmp_path / "state"
    marker = tmp_path / "pwned"
    hostile = f"token=hunter2 $(touch {marker}) `touch {marker}` '; touch {marker}; ' \\\" line\nbreak"
    r = ok(sh(ACQUIRE + LEGACY + 'echo "op=$CB_LIFECYCLE_OPERATION"\n'
              'cb_lifecycle_checkpoint state=recovery_required cause=apply_failed error_code=MANUAL '
              '"error_reason=$HOSTILE"\n'
              'cb_lifecycle_state inspect operation_id="$CB_LIFECYCLE_OPERATION" >/dev/null\n',
              state, {"HOSTILE": hostile}))
    assert not marker.exists()
    inspected = ack(utility({"request": "inspect", "operation_id": op_from(r)}, state).stdout)
    assert len(inspected["journal"]) == 1, "the journal travels as one line the shell never reads"
    assert set(inspected) <= {"operation_id", "kind", "action", "state", "generation", "sequence", "status",
                              "reported", "outcome", "checkpoint", "journal"}
    reason = journal_of(state, op_from(r))["checkpoints"][-1]["error"]["reason"]
    assert "hunter2" not in reason and "token (redacted)" in reason
    assert reason.startswith(f"token (redacted) $(touch {marker})"), reason
    assert "hunter2" not in r.stdout + r.stderr


# --- The interpreter, the control plane and the release inventory ----------------------------


@seam
def test_the_system_interpreter_is_resolved_once_and_an_exported_one_is_ignored(tmp_path: Path) -> None:
    state = tmp_path / "state"
    r = ok(sh(ACQUIRE + "cb_lifecycle_python\necho \"py=$_CB_LIFECYCLE_PYTHON\"\n" + LEGACY, state,
              {"_CB_LIFECYCLE_PYTHON": "/bin/false"}))
    assert re.search(rf"^py={re.escape(SYSTEM_PYTHON)}$", r.stdout, re.MULTILINE), r.stdout


@pytest.mark.parametrize("case", ["older than 3.9", "group-writable", "missing"])
def test_without_a_trusted_interpreter_the_utility_is_refused_with_7(case: str, tmp_path: Path) -> None:
    fake = tmp_path / "bundle" / "python" / "bin" / "python3"
    fake.parent.mkdir(parents=True)
    fake.write_text("#!/bin/sh\nexit 1\n" if case == "older than 3.9" else f'#!/bin/sh\nexec {SYSTEM_PYTHON} "$@"\n')
    os.chmod(fake, 0o775 if case == "group-writable" else 0o755)
    candidate = "" if case == "missing" else str(fake)
    r = sh(f'CB_LIFECYCLE_SYSTEM_PYTHON="{tmp_path}/no-python3"\n'
           f'if cb_lifecycle_python {candidate}; then echo "py=$_CB_LIFECYCLE_PYTHON"; else echo "refused $?"; fi\n'
           , None)
    assert "refused 7" in r.stdout, r.stdout + r.stderr
    assert "ERR-TRAP" not in r.stderr


def test_a_fresh_install_may_use_the_verified_bundle_interpreter(tmp_path: Path) -> None:
    fake = tmp_path / "bundle" / "python" / "bin" / "python3"
    fake.parent.mkdir(parents=True)
    fake.write_text(f'#!/bin/sh\nexec {SYSTEM_PYTHON} "$@"\n')
    os.chmod(fake, 0o755)
    r = ok(sh(f'CB_LIFECYCLE_SYSTEM_PYTHON="{tmp_path}/no-python3"\ncb_lifecycle_python "{fake}"\n'
              'echo "py=$_CB_LIFECYCLE_PYTHON"\n', None))
    assert f"py={fake}" in r.stdout


# A utility that must never run: it leaves a marker and acknowledges nothing.
DECOY_UTILITY = 'import os\nopen(os.environ["CB_TEST_MARKER"], "a").close()\n'
COMMIT = "cb_lifecycle_checkpoint state=committed outcome=committed || exit $?\n"


def _plant_decoys(work: Path, perm: int) -> None:
    """Decoy utilities at every place a library that took the working directory for its own would look."""
    for rel in ("lifecycle-state.py", "deploy/scripts/lifecycle-state.py", "../scripts/lifecycle-state.py"):
        decoy = work / rel
        decoy.parent.mkdir(parents=True, exist_ok=True)
        decoy.write_text(DECOY_UTILITY)
        os.chmod(decoy, perm)


@seam
@pytest.mark.parametrize("perm", [0o755, 0o775], ids=["trusted decoys", "untrusted decoys"])
def test_a_piped_library_never_runs_a_utility_from_the_working_directory(perm: int, tmp_path: Path) -> None:
    # curl | sudo bash: the inlined library has no file of its own (BASH_SOURCE is empty), so only
    # the control plane may provide the utility, whatever the caller's working directory holds.
    state = tmp_path / "state"
    work = tmp_path / "checkout" / "work"
    _plant_decoys(work, perm)
    marker = tmp_path / "decoy-ran"
    script = (STRICT + LIB.read_text() + f'\nCB_LIFECYCLE_SYSTEM_PYTHON="{SYSTEM_PYTHON}"\n'
              f'CB_LIFECYCLE_CONTROL_PLANE="{PLANE[-1]}"\n' + ACQUIRE + LEGACY
              + 'echo "op=$CB_LIFECYCLE_OPERATION"\n' + COMMIT)
    r = ok(subprocess.run(["bash"], input=script, capture_output=True, text=True, cwd=work, timeout=60, check=False,
                          env=env_for(state, {"CB_TEST_MARKER": str(marker)})))
    assert not marker.exists(), "a utility from the working directory ran"
    assert journal_of(state, op_from(r))["checkpoints"][-1]["outcome"] == "committed"


def _bundle_with(tmp_path: Path, utility_text: str, perm: int) -> Path:
    """A bundle's deploy tree: the library and, next to it in scripts/, the given utility."""
    deploy = tmp_path / "bundle" / "deploy"
    (deploy / "lib").mkdir(parents=True)
    (deploy / "scripts").mkdir()
    shutil.copyfile(LIB, deploy / "lib" / "lifecycle.sh")
    (deploy / "scripts" / "lifecycle-state.py").write_text(utility_text)
    os.chmod(deploy / "scripts" / "lifecycle-state.py", perm)
    return deploy


@seam
def test_a_sourced_library_skips_an_untrusted_neighbour_for_the_control_plane(tmp_path: Path) -> None:
    state = tmp_path / "state"
    deploy = _bundle_with(tmp_path, DECOY_UTILITY, 0o775)
    marker = tmp_path / "decoy-ran"
    extra = {"CB_TEST_MARKER": str(marker)}
    r = ok(sh(ACQUIRE + LEGACY + 'echo "op=$CB_LIFECYCLE_OPERATION"\n' + COMMIT, state, extra,
              head=prelude(deploy / "lib" / "lifecycle.sh", PLANE[-1])))
    assert not marker.exists()
    assert journal_of(state, op_from(r))["checkpoints"][-1]["outcome"] == "committed"
    # With no trusted copy anywhere, nothing runs and the refusal names what was passed over.
    r = sh(ACQUIRE + LEGACY, state, extra, head=prelude(deploy / "lib" / "lifecycle.sh", tmp_path / "no-plane"))
    assert r.returncode == 7, r.stderr
    assert f"{deploy}/scripts/lifecycle-state.py is not trusted" in r.stderr
    assert not marker.exists()


@seam
def test_a_sourced_library_runs_the_trusted_utility_of_its_own_bundle_first(tmp_path: Path) -> None:
    # The library and the utility speak one protocol, so a bundle's pair stays together.
    state = tmp_path / "state"
    real = PLANE[-1] / "lifecycle-state.py"
    wrapper = ('import os, runpy, sys\nopen(os.environ["CB_TEST_MARKER"], "a").close()\n'
               f"sys.argv[0] = {str(real)!r}\nrunpy.run_path({str(real)!r}, run_name='__main__')\n")
    deploy = _bundle_with(tmp_path, wrapper, 0o755)
    marker = tmp_path / "bundle-utility-ran"
    r = ok(sh(ACQUIRE + LEGACY + 'echo "op=$CB_LIFECYCLE_OPERATION"\n' + COMMIT, state, {"CB_TEST_MARKER": str(marker)},
              head=prelude(deploy / "lib" / "lifecycle.sh", tmp_path / "no-plane")))
    assert marker.exists()
    assert journal_of(state, op_from(r))["checkpoints"][-1]["outcome"] == "committed"


def test_the_control_plane_is_installed_whole_and_replaced_atomically(tmp_path: Path) -> None:
    plane = tmp_path / "usr-local-lib-circuitbreaker"
    for _ in range(2):  # an upgrade replaces what the install put there
        ok(sh(f'cb_lifecycle_install_control_plane "{ROOT / "deploy"}" "{plane}"\n', None))
    expected = {
        "lifecycle.sh": (ROOT / "deploy" / "lib" / "lifecycle.sh", 0o644),
        "lifecycle-state.py": (UTILITY, 0o755),
        "bundle-signature.sh": (ROOT / "deploy" / "lib" / "bundle-signature.sh", 0o644),
        "release-retention.sh": (ROOT / "deploy/lib/release-retention.sh", 0o644),
        "rollback-release.sh": (ROOT / "deploy/scripts/rollback-release.sh", 0o755),
    }
    assert sorted(p.name for p in plane.iterdir()) == sorted(expected)
    for name, (source, want) in expected.items():
        assert (plane / name).read_bytes() == source.read_bytes(), name
        assert mode(plane / name) == want, name
    assert mode(plane) == 0o755
    # The installed utility runs from the control plane, outside any release tree.
    r = subprocess.run([str(plane / "lifecycle-state.py")], input=b"{}", capture_output=True, timeout=60, check=False)
    assert r.returncode == 2 and b"request must be one of" in r.stderr


def test_an_incomplete_bundle_installs_nothing(tmp_path: Path) -> None:
    deploy = tmp_path / "deploy"
    shutil.copytree(ROOT / "deploy" / "lib", deploy / "lib")
    (deploy / "scripts").mkdir()
    plane = tmp_path / "plane"
    r = sh(f'if cb_lifecycle_install_control_plane "{deploy}" "{plane}"; then echo ok; else echo "refused $?"; fi\n', None)
    assert "refused 7" in r.stdout, r.stdout + r.stderr
    assert "lifecycle-state.py" in r.stderr
    assert not plane.exists() or list(plane.iterdir()) == []


SETUP_FUNCTION = re.compile(r"^stage9_install_lifecycle_control_plane\(\) \{\n.*?^\}$", re.MULTILINE | re.DOTALL)
SETUP_HARNESS = """\
set -Eeuo pipefail
cb_detail() {{ echo "DETAIL|$1"; }}
cb_fail() {{ echo "FAIL|$1"; echo "HINT|${{2:-}}"; exit 1; }}
{function}
stage9_install_lifecycle_control_plane
echo DONE
"""


@pytest.mark.parametrize("complete", [True, False], ids=["complete bundle", "bundle without the utility"])
def test_setup_installs_the_control_plane_or_fails_the_install(complete: bool, tmp_path: Path) -> None:
    text = SETUP_SH.read_text()
    match = SETUP_FUNCTION.search(text)
    assert match, "deploy/setup.sh defines stage9_install_lifecycle_control_plane"
    body = match.group(0)
    assert "|| true" not in body and "cb_warn" not in body, "a failed control plane fails the install"
    stage9 = re.search(r"^stage9_install_cb_cli\(\) \{\n.*?^\}$", text, re.MULTILINE | re.DOTALL)
    assert stage9 and re.search(r"^  stage9_install_lifecycle_control_plane$", stage9.group(0), re.MULTILINE)
    deploy = tmp_path / "opt" / "deploy"
    shutil.copytree(ROOT / "deploy" / "lib", deploy / "lib")
    shutil.copytree(ROOT / "deploy" / "scripts", deploy / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
    if not complete:
        (deploy / "scripts" / "lifecycle-state.py").unlink()
    plane = tmp_path / "plane"
    function = body.replace("/opt/circuitbreaker/deploy", str(deploy)).replace("/usr/local/lib/circuitbreaker", str(plane))
    r = subprocess.run(["bash", "-c", SETUP_HARNESS.format(function=function)], capture_output=True, text=True,
                       timeout=60, check=False, env=env_for(None))
    if complete:
        assert r.returncode == 0 and "DONE" in r.stdout, r.stdout + r.stderr
        assert (plane / "lifecycle-state.py").read_bytes() == UTILITY.read_bytes()
    else:
        assert r.returncode == 1 and "FAIL|" in r.stdout and "DONE" not in r.stdout, r.stdout + r.stderr


def test_install_sh_installs_the_same_control_plane_from_a_checkout_and_fails_without_it() -> None:
    text = INSTALL_SH.read_text()
    loop = re.search(r"for plane_item in ([^;]+); do\n(.*?)\n\s+done\n", text, re.DOTALL)
    assert loop, "install.sh's checkout path installs the lifecycle control plane"
    installed = {(Path(item.split(":")[0]).name, item.split(":")[1]) for item in loop.group(1).split()}
    library = set(re.findall(r'"(?:lib|scripts)/\S+ (\S+) (\d{3})"', LIB.read_text()))
    assert installed == library, "install.sh and cb_lifecycle_install_control_plane install the same files and modes"
    assert "cb_fail" in loop.group(2) and "|| true" not in loop.group(2) and "cb_warn" not in loop.group(2)


def test_the_native_bundle_carries_the_control_plane(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import build_native_release as br
    finally:
        sys.path.remove(str(ROOT / "scripts"))
    tree = tmp_path / "tree"
    for rel in ("python/bin/python3.12", "bin/circuit-breaker", "share/VERSION", "share/build-info.json",
                "share/backend/alembic.ini", "share/frontend/index.html"):
        (tree / rel).parent.mkdir(parents=True, exist_ok=True)
        (tree / rel).write_text(rel)
    monkeypatch.setattr(br, "_write_build_info", lambda *a, **k: None)
    bundle, _ = br.stage_bundle(
        binary_path=tree / "bin" / "circuit-breaker", version=br.VERSION_FILE.read_text().strip(),
        target_os="linux", target_arch="amd64", frontend_dir=tree / "share" / "frontend",
        work_dir=tmp_path / "work", packaging_mode="pbs", tree=tree,
    )
    for rel, source in (("deploy/lib/lifecycle.sh", LIB), ("deploy/scripts/lifecycle-state.py", UTILITY),
                        ("deploy/lib/bundle-signature.sh", ROOT / "deploy" / "lib" / "bundle-signature.sh")):
        assert (bundle / rel).read_bytes() == source.read_bytes(), rel
    assert os.access(bundle / "deploy" / "scripts" / "lifecycle-state.py", os.X_OK)


def test_removal_never_touches_the_audit_history_or_the_control_plane() -> None:
    for script in (UNINSTALL_SH, ROOT / "deploy" / "cli" / "cb", ROOT / "cb"):
        for line in script.read_text().splitlines():
            if re.search(r"\brm\b", line):
                assert "circuitbreaker-lifecycle" not in line, f"{script.name}: {line}"
                assert "/usr/local/lib/circuitbreaker" not in line, f"{script.name}: {line}"
                assert not re.search(r"/var/lib/circuitbreaker\*|/var/lib/circuit\*", line), f"{script.name}: {line}"


# --- started as root -------------------------------------------------------------------------


@pytest.fixture
def dropped_base() -> Iterator[Path]:
    """A temporary directory owned by DROP_UID, below ancestors it may enter and the library trusts."""
    base = Path(tempfile.mkdtemp(prefix="cb-lifecycle-journal-"))
    try:
        os.chown(base, DROP_UID, DROP_GID)
        yield base
    finally:
        shutil.rmtree(base)


@root_only
def test_as_root_every_case_runs_unprivileged(dropped_base: Path) -> None:
    env = env_for(None, {"HOME": str(dropped_base), "TMPDIR": str(dropped_base), "USER": "cb-journal-test",
                         "LOGNAME": "cb-journal-test", "PYTHONDONTWRITEBYTECODE": "1"})
    r = subprocess.run(
        [sys.executable, "-m", "pytest", str(Path(__file__).resolve()), "-q", "-rs", "-p", "no:cacheprovider",
         f"--basetemp={dropped_base / 'pytest'}"],
        capture_output=True, text=True, cwd=dropped_base, env=env, timeout=900, check=False,
        user=DROP_UID, group=DROP_GID, extra_groups=[],
    )
    assert r.returncode == 0, r.stdout + r.stderr
    reasons = re.findall(r"^SKIPPED \[\d+\] \S+: (.*)$", r.stdout, re.MULTILINE)
    assert all(reason.startswith("needs root to drop privileges") for reason in reasons), reasons


@seam
@pytest.mark.parametrize("status", [0, 8, 9])
def test_native_installer_final_result_matches_durable_legacy_outcome(tmp_path: Path, status: int) -> None:
    installer = (ROOT / "install.sh").read_text()
    function = "cb_install_result() {" + installer.split("cb_install_result() {", 1)[1].split("_cb_on_exit() {", 1)[0]
    before = "cb_lifecycle_checkpoint state=checking\n" if status == 0 else "cb_lifecycle_checkpoint state=recovering\n" if status == 8 else ""
    result = sh(ACQUIRE + LEGACY + function + "\n" + before + f'''CB_NPM_RESULT=true
CB_LIFECYCLE_ACTION=update
CB_EXPECTED_VERSION=0.4.7
CB_LIFECYCLE_SOURCE_VERSION=0.4.6
_CB_RELEASE_BACKUP=/tmp/snapshot.tar.gz
cb_install_result {status} || code=$?
echo "op=$CB_LIFECYCLE_OPERATION"
''', tmp_path / "state")
    assert result.returncode == 0, result.stderr
    encoded = next(line.removeprefix("CIRCUITBREAKER_RESULT=") for line in result.stdout.splitlines() if line.startswith("CIRCUITBREAKER_RESULT="))
    document = LS.parse_document("result", encoded.encode())
    expected = {0: "committed", 8: "recovered", 9: "recovery_required"}[status]
    assert document["outcome"] == expected
    journal = journal_of(tmp_path / "state", op_from(result))
    assert journal["checkpoints"][-1]["state"] == expected


# AppArmor in a Proxmox LXC refused flock(2) with EACCES on the installer's
# inherited lock descriptor after a policy reload during the upgrade, while the
# kernel still recorded the lock on it. Ownership then comes from fdinfo.
def _held_lock(state: Path, monkeypatch: pytest.MonkeyPatch) -> int:
    prepared = sh("cb_lifecycle_lock_acquire 'test prepare' || exit $?", state)
    assert prepared.returncode == 0, prepared.stderr
    monkeypatch.setenv("CB_LIFECYCLE_ROOT", str(state))
    monkeypatch.delenv("CB_LIFECYCLE_OPERATION", raising=False)
    fd = os.open(state / "private" / "lock", os.O_RDONLY)
    monkeypatch.setenv("CB_LIFECYCLE_LOCK_FD", str(fd))
    return fd


def _refuse_lock_calls_on(fd: int, monkeypatch: pytest.MonkeyPatch) -> None:
    real = LS.fcntl.flock

    def flock(target: int, op: int) -> None:
        if target == fd:
            raise PermissionError(errno.EACCES, "Permission denied")
        real(target, op)

    monkeypatch.setattr(LS.fcntl, "flock", flock)


@seam
def test_a_refused_lock_call_on_the_held_descriptor_falls_back_to_fdinfo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fd = _held_lock(tmp_path, monkeypatch)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _refuse_lock_calls_on(fd, monkeypatch)
        tree = LS.open_tree()
        assert tree is not None
        assert LS.require_lock(tree) == ""
    finally:
        os.close(fd)


@seam
def test_a_refused_lock_call_on_a_descriptor_without_the_lock_is_still_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fd = _held_lock(tmp_path, monkeypatch)
    holder = os.open(tmp_path / "private" / "lock", os.O_RDONLY)
    try:
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _refuse_lock_calls_on(fd, monkeypatch)
        tree = LS.open_tree()
        assert tree is not None
        with pytest.raises(LS.StateError, match="held through CB_LIFECYCLE_LOCK_FD"):
            LS.require_lock(tree)
    finally:
        os.close(holder)
        os.close(fd)


@seam
def test_the_shell_proves_a_held_descriptor_through_fdinfo_when_flock_is_refused(tmp_path: Path) -> None:
    fake = tmp_path / "bin"
    fake.mkdir()
    real_flock = shutil.which("flock")
    assert real_flock
    # Refuse only a lock call on an inherited descriptor number, as AppArmor did; probes on fresh files pass.
    (fake / "flock").write_text(
        f'#!/bin/bash\n[[ "${{@: -1}}" == "$CB_TEST_REFUSE_FD" ]] && {{ echo "flock: $CB_TEST_REFUSE_FD: Permission denied" >&2; exit 1; }}\nexec {real_flock} "$@"\n'
    )
    (fake / "flock").chmod(0o755)
    result = sh(
        "cb_lifecycle_lock_acquire 'install.sh upgrade' || exit $?\n"
        "fd=$CB_LIFECYCLE_LOCK_FD\n"
        "_cb_lifecycle_lstat \"$CB_LIFECYCLE_ROOT/private/lock\"\n"
        "export CB_TEST_REFUSE_FD=$fd PATH=" + str(fake) + ":$PATH\n"
        "_cb_lifecycle_fd_holds \"$fd\" \"$CB_LIFECYCLE_ROOT/private/lock\" \"$_CB_LC_ID\" && echo HELD\n",
        tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("HELD"), result.stdout + result.stderr
