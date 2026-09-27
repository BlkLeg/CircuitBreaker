#!/usr/bin/env python3
"""Decide whether a finished workflow run deserves a Discord message, and send it.

.github/workflows/notify.yml runs this on every ``workflow_run: completed``
event for the workflows it watches. The rule is "tell the maintainer when the
state of the project changes, and only then":

* a run that failed on ``main`` or ``dev``, or a scheduled or manually
  dispatched run that failed anywhere, is an alert (pinging the maintainer);
* a successful run on the same terms whose previous completed run of the same
  workflow on the same branch failed is a recovery;
* everything else — pull-request runs, pushes to feature branches, a green run
  after a green run, cancellations — is silence.

Pull-request runs are excluded on purpose: a red PR is already in front of its
author, and Dependabot alone produced most of the red runs in September 2026.
The previous run's conclusion is looked up by the workflow (``gh api``) and
passed in, so this module stays pure and testable.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from notify_discord import Notification, send

WATCHED_BRANCHES = frozenset({"main", "dev"})
UNATTENDED_EVENTS = frozenset({"schedule", "workflow_dispatch"})
FAILED = frozenset({"failure", "timed_out", "startup_failure"})


def is_watched(run: Mapping[str, Any]) -> bool:
    """Whether a run's outcome is about the project rather than a proposal."""
    event = str(run.get("event", ""))
    if event in UNATTENDED_EVENTS:
        return True
    return event == "push" and str(run.get("head_branch", "")) in WATCHED_BRANCHES


def decide(run: Mapping[str, Any], previous_conclusion: str) -> Notification | None:
    """Return the notification for ``run``, or ``None`` when nothing changed.

    ``previous_conclusion`` is the conclusion of the prior completed run of the
    same workflow on the same branch, or "" when there is none.
    """
    if not is_watched(run):
        return None
    conclusion = str(run.get("conclusion") or "")
    name = str(run.get("name", "workflow"))
    branch = str(run.get("head_branch") or "?")
    fields = (
        ("Branch", branch),
        ("Trigger", str(run.get("event", "?"))),
        ("Commit", str(run.get("head_sha", ""))[:10] or "?"),
    )
    url = str(run.get("html_url", ""))
    subject = str((run.get("head_commit") or {}).get("message", "")).splitlines()[:1]
    body = subject[0] if subject else ""

    if conclusion in FAILED:
        return Notification(
            level="failure",
            title=f"{name} failed on {branch}",
            body=body,
            url=url,
            fields=fields,
        )
    if conclusion == "success" and previous_conclusion in FAILED:
        return Notification(
            level="success",
            title=f"{name} recovered on {branch}",
            body=body,
            url=url,
            fields=fields,
        )
    return None


def main(argv: Sequence[str] | None = None) -> int:
    """Read the ``workflow_run`` event, decide, and send; always exits 0."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--event-path", default=os.environ.get("GITHUB_EVENT_PATH", ""))
    parser.add_argument("--previous-conclusion", default="")
    parser.add_argument(
        "--dry-run", action="store_true", help="print the decision, send nothing"
    )
    args = parser.parse_args(argv)

    event = json.loads(Path(args.event_path).read_text(encoding="utf-8"))
    run = event.get("workflow_run") or {}
    note = decide(run, args.previous_conclusion)
    if note is None:
        print(
            f"no notification: {run.get('name')} {run.get('conclusion')} on {run.get('head_branch')} ({run.get('event')})"
        )
        return 0
    if note.level == "failure":
        mention = os.environ.get("DISCORD_MENTION_USER_ID", "").strip()
        note = Notification(
            note.level, note.title, note.body, note.url, note.fields, mention
        )
    print(f"notification: {note.title}")
    if not args.dry_run:
        try:
            send(note)
        except ValueError as exc:
            print(f"::warning::{exc}; notification dropped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
