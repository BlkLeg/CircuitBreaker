#!/usr/bin/env python3
"""Post a maintainer notification to a Discord channel webhook.

Every automation that needs a human's attention (a red run on ``main``, a
release draft waiting for approval, a ledger row about to expire) reports
through this one script, so the message shape, the mention policy and the
failure handling live in one place.

The webhook URL is a secret and comes only from ``DISCORD_WEBHOOK_URL``. When it
is unset the script says so and exits 0: forks, local runs and a repository
that has not configured Discord yet must not go red because nobody is
listening. A delivery failure is likewise reported as a warning and exits 0 —
a notification is never a reason to fail the job that sent it. Only a usage
error exits non-zero.

Message text routinely carries attacker-influenced strings (branch names,
commit subjects, issue titles), so ``allowed_mentions`` is always explicit:
nothing in the text can ping ``@everyone`` or a role. The one mention allowed
is the maintainer's own user id from ``DISCORD_MENTION_USER_ID``, and only when
the caller asks for it with ``--mention``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

WEBHOOK_ENV = "DISCORD_WEBHOOK_URL"
MENTION_ENV = "DISCORD_MENTION_USER_ID"

# Discord's documented embed limits.
TITLE_LIMIT = 256
DESCRIPTION_LIMIT = 4096
FIELD_NAME_LIMIT = 256
FIELD_VALUE_LIMIT = 1024
FIELD_COUNT_LIMIT = 25

WEBHOOK_HOSTS = frozenset(
    {"discord.com", "discordapp.com", "ptb.discord.com", "canary.discord.com"}
)
WEBHOOK_PATH_PREFIX = "/api/webhooks/"

LEVEL_COLOURS = {
    "info": 0x3B82F6,
    "success": 0x16A34A,
    "warning": 0xD97706,
    "failure": 0xDC2626,
}

MAX_ATTEMPTS = 3
REQUEST_TIMEOUT_SECONDS = 10.0
USER_AGENT = "circuit-breaker-notify (https://github.com/BlkLeg/CircuitBreaker, 1)"


@dataclass(frozen=True)
class Notification:
    """One message: a coloured embed plus an optional ping for the maintainer."""

    level: str
    title: str
    body: str = ""
    url: str = ""
    fields: Sequence[tuple[str, str]] = field(default_factory=tuple)
    mention_user_id: str = ""


def _clip(text: str, limit: int) -> str:
    """Shorten ``text`` to ``limit`` characters, marking the cut."""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def build_payload(note: Notification) -> dict[str, Any]:
    """Return the Discord webhook JSON for ``note``, within Discord's limits."""
    if note.level not in LEVEL_COLOURS:
        raise ValueError(
            f"unknown level {note.level!r}; expected one of {sorted(LEVEL_COLOURS)}"
        )
    embed: dict[str, Any] = {
        "title": _clip(note.title, TITLE_LIMIT),
        "color": LEVEL_COLOURS[note.level],
    }
    if note.body:
        embed["description"] = _clip(note.body, DESCRIPTION_LIMIT)
    if note.url:
        embed["url"] = note.url
    if note.fields:
        embed["fields"] = [
            {
                "name": _clip(name, FIELD_NAME_LIMIT),
                "value": _clip(value, FIELD_VALUE_LIMIT),
                "inline": True,
            }
            for name, value in list(note.fields)[:FIELD_COUNT_LIMIT]
        ]
    payload: dict[str, Any] = {"embeds": [embed], "allowed_mentions": {"parse": []}}
    if note.mention_user_id:
        if not note.mention_user_id.isdigit():
            raise ValueError(f"{MENTION_ENV} must be a numeric Discord user id")
        payload["content"] = f"<@{note.mention_user_id}>"
        payload["allowed_mentions"] = {"parse": [], "users": [note.mention_user_id]}
    return payload


def mention_from_env(raw: str) -> str:
    """Return the Discord user id in ``raw``, or "" when it is not one.

    Accepts the bare snowflake or Discord's own ``<@id>`` / ``<@!id>`` form. A
    username (``shawnji.dev``) cannot be pinged through a webhook, and a bad
    value must cost only the ping, never the message: it warns and returns "".
    """
    value = raw.strip()
    if value.startswith("<@") and value.endswith(">"):
        value = value[2:-1].lstrip("!")
    if value.isdigit():
        return value
    if value:
        print(
            f"::warning::{MENTION_ENV} is not a numeric Discord user id (Developer "
            "Mode, right-click your name, Copy User ID); sending without a ping"
        )
    return ""


def validate_webhook_url(url: str) -> None:
    """Refuse anything that is not an https Discord webhook URL.

    The secret is the only input deciding where message text is sent, so a
    mis-pasted value must not turn this script into a way to post repository
    data to an arbitrary host.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in WEBHOOK_HOSTS:
        raise ValueError(f"{WEBHOOK_ENV} is not an https Discord webhook URL")
    if not parsed.path.startswith(WEBHOOK_PATH_PREFIX):
        raise ValueError(f"{WEBHOOK_ENV} is not a Discord webhook path")


Opener = Callable[[urllib.request.Request, float], Any]
Sleeper = Callable[[float], None]


def _default_opener(request: urllib.request.Request, timeout: float) -> Any:
    return urllib.request.urlopen(request, timeout=timeout)


def deliver(
    url: str,
    payload: dict[str, Any],
    opener: Opener | None = None,
    sleep: Sleeper | None = None,
) -> bool:
    """POST ``payload`` to ``url``; retry on 429 and 5xx. Return whether it landed."""
    validate_webhook_url(url)
    # Resolved per call, not bound as a default, so a caller (or a test) that
    # swaps the module's opener is honoured.
    open_request = opener or _default_opener
    pause = sleep or time.sleep
    data = json.dumps(payload).encode("utf-8")
    for attempt in range(1, MAX_ATTEMPTS + 1):
        request = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        )
        try:
            with open_request(request, REQUEST_TIMEOUT_SECONDS):
                return True
        except urllib.error.HTTPError as exc:
            # An HTTPError holds the response open; close it on every path.
            with exc:
                if attempt == MAX_ATTEMPTS or not (exc.code == 429 or exc.code >= 500):
                    print(
                        f"::warning::Discord webhook answered HTTP {exc.code}; notification dropped"
                    )
                    return False
                retry_after = 1.0
                if exc.code == 429:
                    try:
                        retry_after = float(
                            json.loads(exc.read() or b"{}").get("retry_after", 1.0)
                        )
                    except (ValueError, AttributeError):
                        retry_after = 1.0
            pause(min(retry_after, 30.0))
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == MAX_ATTEMPTS:
                print(
                    f"::warning::Discord webhook unreachable ({exc.__class__.__name__}); notification dropped"
                )
                return False
            pause(float(attempt))
    return False


def send(
    note: Notification,
    env: dict[str, str] | None = None,
    opener: Opener | None = None,
) -> bool:
    """Send ``note`` using the webhook in ``env``; a missing webhook is a no-op."""
    environ = os.environ if env is None else env
    url = environ.get(WEBHOOK_ENV, "").strip()
    if not url:
        print(f"{WEBHOOK_ENV} is not set; skipping notification: {note.title}")
        return False
    return deliver(url, build_payload(note), opener=opener)


def _parse_field(raw: str) -> tuple[str, str]:
    name, sep, value = raw.partition("=")
    if not sep or not name:
        raise argparse.ArgumentTypeError(f"--field expects name=value, got {raw!r}")
    return name, value


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point; see the module docstring."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--level", choices=sorted(LEVEL_COLOURS), default="info")
    parser.add_argument("--title", required=True)
    body = parser.add_mutually_exclusive_group()
    body.add_argument("--body", default="")
    body.add_argument("--body-file", default="")
    parser.add_argument("--url", default="")
    parser.add_argument(
        "--field", action="append", type=_parse_field, default=[], metavar="NAME=VALUE"
    )
    parser.add_argument(
        "--mention",
        action="store_true",
        help=f"ping the user in {MENTION_ENV}, if set",
    )
    args = parser.parse_args(argv)

    text = args.body
    if args.body_file:
        with open(args.body_file, encoding="utf-8") as handle:
            text = handle.read()
    mention = mention_from_env(os.environ.get(MENTION_ENV, "")) if args.mention else ""
    note = Notification(
        level=args.level,
        title=args.title,
        body=text,
        url=args.url,
        fields=tuple(args.field),
        mention_user_id=mention,
    )
    try:
        send(note)
    except ValueError as exc:
        print(f"::warning::{exc}; notification dropped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
