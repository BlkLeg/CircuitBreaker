"""B44: the `discovery.jobs` consumer runs no scan, because nothing feeds it.

`workers/discovery.py` declares a DISCOVERY JetStream stream on `discovery.jobs`
and subscribes a queue group to it. Nothing in this repository has ever
published to that subject — outside its own tests the subject appears in
`workers/discovery.py` and nowhere else in the tree, in any language, and it has
been that way since the module was added.

The tempting reading is "a publisher was lost in a refactor, so scheduled
discovery is silently not running". It is the wrong reading, and the consumer
body is what settles it: the handler ran masscan, then nmap, and then
**discarded both results**. No `ScanResult` row, no `ScanJob` transition, no
broadcast — nothing a scan is for. It was never the other half of anything.
Scheduled discovery runs through `discovery_service.execute_scan_job`, which
either scans from the server (`run_scan_job`) or dispatches to an agent
(`agent_discovery.dispatch_discovery_job`); both are wired, tested and
unrelated to this queue.

What the handler *was* is a subprocess launcher reachable by anyone who can
publish to the NATS server, taking an unvalidated `target_cidr` straight into
`masscan` argv, inside a container that is deliberately given ambient
CAP_NET_RAW (`docker/supervisord.mono.conf`). A port scanner for hire, in
exchange for no product function at all. So the scan execution goes; a message
that somehow arrives is logged loudly and consumed rather than acted on.

Retiring the worker process, its supervisord program and its `topology.py`
entry is the rest of this and spans files outside this change.

A note on how these are written. "Nothing publishes to this subject" is the
premise the whole finding rests on, and a test that only asserts the premise
cannot fail on the defect — it was as true with the scanner in place as it is
now. So the premise is not asserted on its own anywhere below: it is the
antecedent of `test_no_publisher_exists_for_the_subject_the_worker_consumes`,
which requires that *while* no publisher exists the module carries no way to
execute a scanner. Add a publisher and that test starts demanding a result path
and argument validation instead of passing quietly.
"""

import ast
import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any

_BACKEND = Path(__file__).resolve().parents[2]
_REPO = _BACKEND.parents[1]

#: Every scanner this worker has ever launched, plus the near neighbours a
#: re-arming edit would reach for. Matched as an import name and as the first
#: word of a string literal, which is how argv lists are written.
_SCANNERS = frozenset({"masscan", "nmap", "zmap", "rustscan"})

#: Ways to start a process, by attribute name.
_SPAWNERS = frozenset(
    {"create_subprocess_exec", "create_subprocess_shell", "Popen", "check_output", "check_call"}
)


class _FakeMsg:
    def __init__(self, payload: dict) -> None:
        self.data = json.dumps(payload).encode()
        self.subject = "discovery.jobs"
        self.acked = False
        self.naked = False

    async def ack(self) -> None:
        self.acked = True

    async def nak(self) -> None:
        self.naked = True


def _deliver(payload: dict) -> _FakeMsg:
    from app.workers import discovery

    msg = _FakeMsg(payload)
    asyncio.run(discovery.process_job(msg, asyncio.Semaphore(1)))
    return msg


def _executable_scanner_references(source: str) -> list[str]:
    """Scanner-launching code in `source`, ignoring anything only said in prose.

    Parsed rather than grepped on purpose: the module docstring has to be free
    to explain at length what the handler used to run and why it must not run
    it again, and a substring search for "masscan" would make writing that
    explanation the thing that fails the test. What is looked for is an import
    of a scanner module, a string literal whose first word is a scanner binary
    (how an argv list is spelled), and any call that starts a process.
    """
    references: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            references += [
                f"import {alias.name}"
                for alias in node.names
                if alias.name.split(".")[0] in _SCANNERS
            ]
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] in _SCANNERS:
                references.append(f"from {node.module} import ...")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            first_word = node.value.strip().split(" ")[0].split("/")[-1]
            if first_word in _SCANNERS:
                references.append(f"argv literal {node.value[:48]!r}")
        elif isinstance(node, ast.Attribute) and node.attr in _SPAWNERS:
            references.append(f"process spawn via {node.attr}")
    return sorted(set(references))


def test_a_message_on_discovery_jobs_does_not_launch_a_scanner(monkeypatch: Any) -> None:
    """The assertion that matters: the handler must not shell out. `masscan` and
    `nmap` are the only two subprocesses this module ever launched, and both go
    through `asyncio.create_subprocess_exec` or a `nmap.PortScanner`, so a
    recorder on the former catches the path a publisher would have opened."""
    spawned: list[tuple] = []

    async def _record(*args: Any, **kwargs: Any) -> Any:
        spawned.append(args)
        raise AssertionError("the discovery worker spawned a scanner")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _record)

    msg = _deliver({"target_cidr": "203.0.113.0/24", "nmap_args": "-T4 -F"})

    assert spawned == [], (
        "a message on discovery.jobs made the worker execute a scan against "
        f"{spawned!r}; nothing publishes to that subject and the handler has no "
        "result path, so the scan is pure remote-triggered subprocess surface"
    )
    assert msg.acked, "the message was left on a work queue to be redelivered forever"


def test_the_worker_carries_no_scanner_launchers(monkeypatch: Any) -> None:
    """Structural half of the same point. The helpers cannot be reached by any
    publisher this tree contains, so their presence is only a promise that the
    next edit can re-arm them by accident."""
    from app.workers import discovery

    for gone in ("_run_masscan", "_run_nmap"):
        assert not hasattr(discovery, gone), (
            f"workers/discovery.py still defines {gone}; the DISCOVERY consumer "
            "has no publisher and no result path, so it must not carry a scanner"
        )


def test_a_malformed_message_is_consumed_rather_than_redelivered() -> None:
    """The poison-pill loop, which is a different failure from the one above.

    A well-formed message used to be acked at the end of a successful scan; a
    message the handler could not parse was `nak`ed, and DISCOVERY is a
    `WORK_QUEUE` stream, so nak means redeliver — the same undecodable body
    coming back until `max_age` expires it, each round through a handler that
    logs an error. One malformed publish was an hour of log flood.

    So this pins both directions explicitly: acked, and *not* naked. The
    handler no longer parses the payload at all, which is what makes both true
    at once, and asserting the nak separately is what keeps a future "let's be
    careful and retry the ones we could not read" from reintroducing the loop.
    """
    from app.workers import discovery

    msg = _FakeMsg({})
    msg.data = b"not json at all"
    asyncio.run(discovery.process_job(msg, asyncio.Semaphore(1)))

    assert msg.acked, "a malformed discovery.jobs message would be redelivered forever"
    assert not msg.naked, (
        "the handler nak'd a message it could not read. DISCOVERY is a WORK_QUEUE "
        "stream: nak is redeliver, and a body nothing can parse is not a body a "
        "retry will parse — it comes back until max_age, logging an error each time"
    )


def test_no_publisher_exists_for_the_subject_the_worker_consumes() -> None:
    """No publisher, therefore no scanner — asserted as one implication.

    The grep on its own is the premise of B44 and was true before the fix as
    well as after, so on its own it could never fail on the defect it
    accompanies. What is asserted here is the consequence: for as long as
    nothing in the tree publishes to `discovery.jobs`, `workers/discovery.py`
    must contain no way to launch a scanner, because every scan it could run
    would have been ordered by something outside this repository entirely.

    The day a publisher is added, the antecedent goes false and this test stops
    constraining the module — deliberately, because at that point the module
    needs a result path and validated arguments, and those are what the new
    publisher's own tests have to demand. Adding a publisher purely to switch
    this test off would leave `test_a_message_on_discovery_jobs_does_not_launch_a_scanner`
    still standing.
    """
    worker = _BACKEND / "src/app/workers/discovery.py"
    hits = subprocess.run(
        [
            "grep",
            "-rlF",
            "--include=*.py",
            "--include=*.go",
            "--include=*.ts",
            "--include=*.tsx",
            "--exclude-dir=tests",
            "--exclude-dir=e2e",
            "--exclude-dir=.venv",
            "--exclude-dir=node_modules",
            "--exclude-dir=.git",
            # Registered git worktrees live under .claude/ and hold FULL
            # copies of the source tree, so without this the scan reports
            # workers/discovery.py once per worktree — as a "publisher",
            # against paths that are not this checkout. Unrelated to slice
            # 4.x; the same hazard is why the Phase 4 ratchets ask git what
            # is tracked instead of walking the filesystem.
            "--exclude-dir=.claude",
            '"discovery.jobs"',
            str(_REPO),
        ],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.split()
    publishers = sorted(h for h in hits if Path(h).resolve() != worker.resolve())

    if publishers:
        # Not a failure by itself — but it is the one event that makes the
        # scanner ban below negotiable, so it has to be loud rather than
        # silently permissive.
        raise AssertionError(
            f"`discovery.jobs` is now named outside workers/discovery.py: {publishers}. "
            "If that is a real publisher, this worker needs a result path and "
            "validated arguments before it needs a scanner again (B44); update this "
            "test deliberately, with those in the same change."
        )

    scanners = _executable_scanner_references(worker.read_text())
    assert scanners == [], (
        "nothing in the tree publishes to `discovery.jobs`, yet "
        f"workers/discovery.py can still launch a scanner: {scanners}. Every scan "
        "it runs is therefore ordered by something outside this repository, from a "
        "process holding ambient CAP_NET_RAW, and thrown away afterwards."
    )
