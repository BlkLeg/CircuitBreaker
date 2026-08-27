# apps/backend/tests/services/test_scheduler_job_registration.py
"""Who registers which scheduled job, and what misfire grace actually buys.

Two defects meet here, both about registration rather than about the work the
jobs do.

**B43 — the scan-result purge was registered twice.** `app.main.lifespan`
registers `discovery_service.purge_old_scan_results` at 03:00 under the id
`purge_old_scan_results`; `core.scheduler.reload_discovery_jobs` registered the
same callable, on the same trigger, under the id `discovery_purge`. Every
discovery-profile write therefore left two copies of one purge in the
scheduler. `SingleOwnerScheduler` keys its advisory lock on the *job id*, so two
ids are two locks and the copies did not exclude each other — what actually
kept the DELETE from running twice was the callable's own inner
`run_with_advisory_lock("discovery_purge")`, a lock the scheduler knows nothing
about and that a maintainer could reasonably delete on the grounds that
`SingleOwnerScheduler` makes it redundant. So the SRV-02 guarantee that the
id-keyed lock exists to provide was not covering this job at all.

**R11 — the 02:00 snapshot's registration justified `misfire_grace_time=3600`
by a case the parameter cannot cover.** It named a process that was not running
at 02:00 as the thing the grace window rescues, which it is not:
`SingleOwnerScheduler` inherits APScheduler's default in-memory job store and
the lifespan builds a new instance on every boot, so a process that comes up at
02:30 holds no fire time from the 02:00 it missed — misfire grace forgives a
fire time the scheduler *is* holding, and there is none. The parameter is still
worth having for the case it does cover, and the two tests at the bottom of
this file split those cases apart: one executes the difference, the other
refuses to let any comment or docstring in the backend restate the wrong half.

That second test is deliberately tree-wide rather than pointed at
`src/app/main.py`. R11 was reported against a comment *and* a test that both
carried the claim, and the first attempt to close it fixed the comment, pinned
only `main.py`, and left the assertion in
`tests/services/test_scheduled_snapshot_registration.py` saying the wrong thing
with nothing failing on it. A test that asserts a protection the code does not
provide is the whole of what R11 is about, so the pin has to reach every file
that is in a position to make that mistake — which is all of them.
"""

import ast
import io
import re
import tokenize
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from apscheduler.triggers.cron import CronTrigger

from app.core import scheduler as scheduler_module
from app.core.scheduler import SingleOwnerScheduler, reload_discovery_jobs, run_scheduled_snapshot
from app.services.discovery_scheduler import purge_old_scan_results

SNAPSHOT_JOB_ID = "daily_db_snapshot"
#: The id `app.main.lifespan` registers the scan-result purge under.
LIFESPAN_PURGE_JOB_ID = "purge_old_scan_results"
#: The grace window `app.main.lifespan` gives the nightly jobs.
NIGHTLY_MISFIRE_GRACE_S = 3600

_BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture
def fresh_scheduler():  # type: ignore[no-untyped-def]
    """A scheduler of this test's own, bound in place of the process-global one.

    Left unstarted deliberately: `add_job` on a stopped scheduler parks the job
    in `_pending_jobs`, which `get_job`/`get_jobs` still read, so registration
    is observable without an event loop and without firing anything at 02:00.
    """
    previous = scheduler_module.get_scheduler()
    fresh = SingleOwnerScheduler()
    scheduler_module.set_scheduler_instance(fresh)
    try:
        yield fresh
    finally:
        scheduler_module.set_scheduler_instance(previous)


def _jobs_wrapping(scheduler, target):  # type: ignore[no-untyped-def]
    """Every registered job whose body is `target`, seen through `single_owner`.

    `SingleOwnerScheduler.add_job` replaces the callable with a
    `functools.wraps` closure, so the registered `job.func` is not `target` by
    identity — but `wraps` copies `__module__` and `__qualname__`, and that pair
    is what identifies the function underneath. Comparing it is the only way to
    ask "how many copies of this job are scheduled?" without trusting the ids,
    which is exactly what B43 was about.
    """
    ref = (target.__module__, target.__qualname__)
    return [j for j in scheduler.get_jobs() if (j.func.__module__, j.func.__qualname__) == ref]


def _lifespan_registers_purge(scheduler) -> None:  # type: ignore[no-untyped-def]
    """Register the purge the way `app.main.lifespan` does."""
    scheduler.add_job(
        purge_old_scan_results,
        trigger=CronTrigger(hour=3, minute=0),
        id=LIFESPAN_PURGE_JOB_ID,
        replace_existing=True,
        misfire_grace_time=NIGHTLY_MISFIRE_GRACE_S,
    )


# ── B43: one purge, one job id ────────────────────────────────────────────────


def test_reload_discovery_jobs_does_not_register_the_scan_result_purge(fresh_scheduler, db_session):
    """The purge belongs to the lifespan, which runs on every boot, not to a
    discovery-profile write. Registering it here as well is what produced the
    second 03:00 copy under a second lock name."""
    reload_discovery_jobs(db_session)

    copies = _jobs_wrapping(fresh_scheduler, purge_old_scan_results)
    assert copies == [], (
        "reload_discovery_jobs registered the scan-result purge; the lifespan "
        f"already owns it. Registered as: {[j.id for j in copies]}"
    )


def test_a_profile_write_leaves_exactly_one_copy_of_the_scan_result_purge(
    fresh_scheduler, db_session
):
    """The whole of B43 in one assertion: register the purge the way the
    lifespan does, put the scheduler through the profile write that rebuilds
    the discovery jobs, and require that exactly one copy — the lifespan's —
    is still scheduled. Two copies mean two `single_owner` lock names for one
    function, which is the SRV-02 guarantee not holding."""
    _lifespan_registers_purge(fresh_scheduler)

    reload_discovery_jobs(db_session)

    assert [j.id for j in _jobs_wrapping(fresh_scheduler, purge_old_scan_results)] == [
        LIFESPAN_PURGE_JOB_ID
    ], "the scan-result purge is not registered exactly once after a profile write"


# ── R11: what misfire grace does and does not cover ───────────────────────────


def test_a_restart_keeps_no_fire_time_for_misfire_grace_to_forgive(fresh_scheduler):
    """The two cases R11 confused, executed side by side rather than described.

    This started life as a one-line premise guard — a new scheduler carries no
    jobs — which is a property of APScheduler rather than of anything this
    repository decides, and so could not fail however wrong the surrounding
    claim got. It now runs both halves of the distinction the registration
    comment draws, against the value `main.py` actually ships.

    First half, what `misfire_grace_time=3600` genuinely buys. A job the
    scheduler *is* holding a fire time for, whose wakeup lands half an hour
    late — a stalled event loop, a saturated thread pool, a suspended host — is
    still due at 3600, and would not be at APScheduler's default of 1. That
    contrast is the entire justification for the parameter, so it is asserted
    against a second job registered without it rather than described. The
    explicit `next_run_time` in the past is the state a late wakeup leaves a
    job in.

    Second half, the case the parameter cannot reach. `app.main.lifespan`
    constructs a `SingleOwnerScheduler()` per process and the default job store
    is in memory, so the instance that comes up at 02:30 inherits nothing from
    the one that was running yesterday: no jobs at all, and after registering
    the snapshot exactly as the lifespan does, not even a `next_run_time`
    attribute until it starts and computes the *next* one, which is tomorrow's
    02:00. There is no missed fire time for any grace window to forgive, and
    widening the parameter would not create one.

    Revisit this whole test if a persistent job store is ever wired in — both
    halves change at once, and so does the comment at the registration site.
    What must not happen is the comment changing on its own.
    """
    trigger = CronTrigger(hour=2, minute=0)
    tz = trigger.timezone
    missed_at = datetime(2026, 8, 26, 2, 0, tzinfo=tz)
    woke_at = datetime(2026, 8, 26, 2, 30, tzinfo=tz)

    # ── the case the grace window covers ────────────────────────────────────
    fresh_scheduler.add_job(
        run_scheduled_snapshot,
        trigger=trigger,
        id=SNAPSHOT_JOB_ID,
        replace_existing=True,
        misfire_grace_time=NIGHTLY_MISFIRE_GRACE_S,
        next_run_time=missed_at,
    )
    held = fresh_scheduler.get_job(SNAPSHOT_JOB_ID)

    # The same job with the parameter left off, so the assertions below compare
    # against what deleting it would actually do rather than against a number
    # written into this file.
    fresh_scheduler.add_job(
        run_scheduled_snapshot,
        trigger=CronTrigger(hour=2, minute=0),
        id=SNAPSHOT_JOB_ID + "_without_grace",
        replace_existing=True,
        next_run_time=missed_at,
    )
    ungraced = fresh_scheduler.get_job(SNAPSHOT_JOB_ID + "_without_grace")

    # `_get_run_times` is the same call `BaseScheduler._process_jobs` makes to
    # decide what is due; `_process_jobs` then drops any of them that are later
    # than `misfire_grace_time`. Both steps, so this is the real decision.
    due = held._get_run_times(woke_at)
    assert due == [missed_at], (
        "a fire time the scheduler is holding stopped being due after a late "
        f"wakeup; APScheduler returned {due!r}"
    )
    lateness = (woke_at - missed_at).total_seconds()

    # A job registered without the parameter carries no override at all — the
    # window it runs under is the scheduler-wide default, which APScheduler
    # sets to one second.
    assert not hasattr(ungraced, "misfire_grace_time"), (
        "a job registered without misfire_grace_time picked one up anyway "
        f"({ungraced.misfire_grace_time!r}); the comparison below is no longer "
        "against the default"
    )
    default_grace = fresh_scheduler._job_defaults["misfire_grace_time"]
    assert lateness > default_grace, (
        f"APScheduler's default grace is now {default_grace}s, wide enough to "
        f"forgive a {lateness:.0f}s late wakeup on its own. The snapshot's explicit "
        "misfire_grace_time is then buying nothing and the comment at its "
        "registration should say so."
    )
    assert lateness <= held.misfire_grace_time, (
        f"the snapshot is registered with misfire_grace_time={held.misfire_grace_time}, "
        f"which no longer forgives a {lateness:.0f}s late wakeup — the only case the "
        "parameter actually covers."
    )

    # The value under test has to be the value that ships, or the two
    # assertions above are arithmetic on a constant this file made up.
    main_py = (_BACKEND / "src/app/main.py").read_text()
    registration = main_py[main_py.index(f'id="{SNAPSHOT_JOB_ID}"') - 400 :][:600]
    assert f"misfire_grace_time={NIGHTLY_MISFIRE_GRACE_S}" in registration, (
        "the nightly snapshot no longer registers with "
        f"misfire_grace_time={NIGHTLY_MISFIRE_GRACE_S}. At APScheduler's default of "
        f"{default_grace}s a wakeup {lateness:.0f}s late drops the run "
        "and leaves a log line, which is the failure R11's corrected comment exists "
        f"to keep visible.\n{registration}"
    )

    # ── the case it does not ────────────────────────────────────────────────
    after_restart = SingleOwnerScheduler()
    assert after_restart.get_jobs() == [], (
        "a freshly constructed scheduler carried jobs over from another "
        "instance — the job store is no longer in-memory, so the misfire "
        "reasoning at the daily_db_snapshot registration needs revisiting"
    )

    after_restart.add_job(
        run_scheduled_snapshot,
        trigger=CronTrigger(hour=2, minute=0),
        id=SNAPSHOT_JOB_ID,
        replace_existing=True,
        misfire_grace_time=NIGHTLY_MISFIRE_GRACE_S,
    )
    rebooted = after_restart.get_job(SNAPSHOT_JOB_ID)

    assert not hasattr(rebooted, "next_run_time"), (
        "a job registered on a fresh scheduler already carries a fire time "
        f"({getattr(rebooted, 'next_run_time', None)!r}); it can only have come "
        "from a store that outlived the process, which would change what "
        "misfire grace means for this job"
    )

    next_fire = rebooted.trigger.get_next_fire_time(None, woke_at)
    assert next_fire > woke_at, (
        f"the snapshot's first fire after a 02:30 boot is {next_fire!r}, not in the future"
    )
    assert next_fire - missed_at > timedelta(seconds=NIGHTLY_MISFIRE_GRACE_S), (
        f"the first fire a restarted process schedules is {next_fire!r}, which is "
        f"within {NIGHTLY_MISFIRE_GRACE_S}s of the {missed_at!r} it was down for. "
        "The missed run is gone, not graced: nothing about this parameter brings "
        "it back, and only a persistent job store plus an explicit catch-up would."
    )


# ── R11: no comment in the tree may restate the claim ─────────────────────────

#: Verbs that must not be preceded by a negation for a match to count. Written
#: as chained fixed-width lookbehinds because Python's `re` refuses a variable
#: -width one; the corrected comment in `main.py` reads "It does **not** cover a
#: restart", and that sentence must keep passing.
_UNNEGATED = r"(?<!not )(?<!never )(?<!cannot )(?<!n't )(?<!nothing )"

#: Every way the tree currently has of naming "the process was not running".
_A_RESTART = r"(?:restart|reboot|redeploy|downtime|process (?:that )?(?:was|is) down)"

#: The claim R11 is about, in four shapes rather than as three exact
#: substrings. The wordings that shipped, the wordings the review invented to
#: get past an earlier literal ban, and the ones nobody has written yet all
#: reduce to the same four shapes, which is the point of matching a shape.
#: `[^.!?]` keeps every match inside one sentence, so a true statement cannot
#: be assembled out of two neighbouring false-looking halves. The keys are the
#: message a reader gets; the claims themselves are spelled out only in the
#: patterns, because this file is scanned by its own rule.
_FALSE_GRACE_CLAIMS = {
    "a restart still runs the job": re.compile(
        _A_RESTART + r"[^.!?]{0,120}?\bstill\b[^.!?]{0,60}?"
        r"(?:take|takes|taken|run|runs|ran|fire|fires|fired|catch(?:es)? up|happen)",
        re.I | re.S,
    ),
    "grace covers a restart": re.compile(
        r"(?:misfire|grace)[^.!?]{0,160}?"
        + _UNNEGATED
        + r"(?:cover|covers|survive|survives|protect|protects|rescue|save)[^.!?]{0,60}?"
        + _A_RESTART,
        re.I | re.S,
    ),
    "grace reaches back across 02:00": re.compile(
        r"(?:misfire|grace)[^.!?]{0,200}?"
        + _UNNEGATED
        + _A_RESTART
        + r"[^.!?]{0,80}?(?:straddl|spann|spans|across|through|over)[^.!?]{0,40}?"
        r"(?:02:00|2 ?a\.?m)",
        re.I | re.S,
    ),
    # A process that was not running retained no fire time, so prose about the
    # scheduled run it slept past names something that never existed. Kept
    # narrow — the phrase only offends next to a word for the thing that was
    # supposedly missed — because this pattern scans every file in the backend
    # and must not start arguing with prose about unrelated subjects.
    "a scheduled run was missed while the process was down": re.compile(
        r"(?:fire time|run|job|schedul|snapshot|cron|wakeup)[^.!?]{0,80}?slept through"
        r"|slept through[^.!?]{0,80}?(?:fire time|run|job|schedul|snapshot|cron|wakeup)",
        re.I | re.S,
    ),
}


def _prose(source: str) -> list[str]:
    """Every comment and docstring in `source`, and nothing else.

    Comments come from `tokenize` and docstrings from `ast`, deliberately in
    place of a blanket scan of every string literal: the false claim is quoted
    as data in this very file (the patterns above name it), and a test that
    cannot describe the thing it bans is a test nobody can maintain.
    """
    blocks: list[str] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            blocks.append(token.string.lstrip("#").strip())
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            doc = ast.get_docstring(node, clean=True)
            if doc:
                blocks.append(doc)
    return blocks


def test_the_snapshot_registration_does_not_claim_grace_survives_a_restart():
    """R11, pinned across the whole backend rather than at one call site.

    The parameter is fine; the reason given for it was not, and prose that
    promises a protection the code cannot provide is worse than no prose — it
    is what a maintainer weighing whether to keep the parameter reads, and it
    was what the *test* next door asserted, which is worse again. Reading only
    `src/app/main.py` is how the first attempt at this left
    `test_scheduled_snapshot_registration.py` still saying it, so the scan is
    every `.py` file under `src/` and `tests/`: roughly a second, and a new
    file cannot be added outside it.

    Asserted as an absence, so no amount of prose can satisfy it, and matched
    by shape rather than by literal, so rewording the same claim does not slip
    through. Sentences that explicitly deny the claim are what the negation
    lookbehinds exist for and stay legal — saying what misfire grace does not
    do is the correction, not the defect.
    """
    offences: list[str] = []
    scanned = 0
    for root in ("src", "tests"):
        for path in sorted((_BACKEND / root).rglob("*.py")):
            scanned += 1
            for block in _prose(path.read_text()):
                flattened = " ".join(block.split())
                for claim, pattern in _FALSE_GRACE_CLAIMS.items():
                    found = pattern.search(flattened)
                    if found:
                        rel = path.relative_to(_BACKEND)
                        offences.append(f"{rel}: [{claim}] ...{found.group(0)}...")

    assert scanned > 100, f"the scan found only {scanned} files; the tree walk is broken"
    assert offences == [], (
        "prose in the backend still claims misfire_grace_time carries a job "
        "across a process that was not running. It cannot: the job store is in "
        "memory and every job is created fresh at boot, so there is no missed "
        "fire time to grace. Rewrite the claim, do not relax the pattern.\n  "
        + "\n  ".join(offences)
    )


def _registration_comment(source: str, job_id: str) -> str:
    """The comment block attached to `job_id`'s `scheduler.add_job` call.

    Walks back over the whole file rather than a fixed window. An earlier
    version stopped after 40 lines, which was four lines of slack over the
    block it was reading: prepending a paragraph to that comment would have
    silently dropped the top of it out of the assertion below, with nothing
    failing to say so. The loop already terminates on the first non-comment
    line above the block, so the window was doing no work the break was not.
    """
    head = source[: source.index(f'id="{job_id}"')]
    collected: list[str] = []
    for line in reversed(head.splitlines()):
        stripped = line.strip()
        if stripped.startswith("#"):
            collected.append(stripped)
        elif collected:
            break
    assert collected, f"no comment block found above the {job_id} registration"
    return "\n".join(reversed(collected))


def test_the_snapshot_registration_still_addresses_the_restart_case():
    """The positive half of R11, so that the ban above cannot be satisfied by
    deleting the correction along with the claim.

    The registration comment has to keep saying something about a process that
    was not running at 02:00, because that is the reading a maintainer arrives
    with and the parameter's name invites. *What* it may say is constrained by
    the tree-wide ban above; that it says anything at all is constrained here.
    """
    main_py = (_BACKEND / "src/app/main.py").read_text()
    comment = _registration_comment(main_py, SNAPSHOT_JOB_ID)

    assert re.search(_A_RESTART, comment, re.I), (
        "the daily_db_snapshot registration comment no longer mentions a "
        "restart at all. misfire_grace_time reads like it covers one and does "
        "not, so the comment has to say so rather than go quiet.\n" + comment
    )
