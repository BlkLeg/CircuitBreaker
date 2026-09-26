#!/usr/bin/env python3
"""Decide which registry tags and GitHub Release flags a version is entitled to.

GOV-20: promotion of a stable channel is an explicit post-acceptance action. A
release candidate must never move `latest`, and must be marked prerelease on
GitHub so it does not become the "Latest release" a user lands on.

Three publish channels (docs/superpowers/specs/2026-09-22-installer-and-release-design.md §5):

  nightly    moving `:nightly` from a green push to `dev` (amd64 image only)
  candidate  `:<version>-candidate` and `:candidate` — draft GitHub Release
  stable     `:<version>` plus `:latest` when not a prerelease — promote of the
             same digest; no rebuild

Before this existed, release.yml pushed `:${VERSION}` and `:latest` in the same
step and called `gh release create` with no --prerelease, so tagging
v1.0.0-rc.3 would have moved both "latest" pointers to a release candidate.
"""

from __future__ import annotations

import argparse
import re
import sys

# A stable version is exactly MAJOR.MINOR.PATCH with no pre-release suffix.
_STABLE_RE = re.compile(r"^\d+\.\d+\.\d+$")

CHANNELS: tuple[str, ...] = ("nightly", "candidate", "stable")


def is_prerelease(version: str) -> bool:
    """True for anything that is not a bare MAJOR.MINOR.PATCH.

    Deliberately allowlist-shaped rather than blocklist-shaped: an unrecognised
    version string is treated as a prerelease, so a typo can never promote a
    stable channel.

    A leading `v` is stripped so this agrees with `app.core.version.is_prerelease`
    on tag-shaped input. `release.yml` already strips the `v` before calling
    this, so it is a no-op at build time; it exists so the two implementations
    cannot drift, which is the guarantee
    `tests/core/test_version.py::test_agrees_with_release_channel` advertises.
    """
    return not _STABLE_RE.match(version.strip().lstrip("vV"))


def channel_tags(version: str, channel: str = "stable") -> list[str]:
    """The registry tags this version may be published under, per channel.

    stable:    <version>, plus `latest` only when <version> is not a prerelease
               (GOV-20: an rc never moves latest).
    candidate: <version>-candidate and the moving `candidate` tag — the draft
               release's image, promoted to stable by retagging the same digest.
    nightly:   the moving `nightly` tag from a green push to dev.
    """
    value = version.strip()
    if not value:
        raise SystemExit("release_channel: version must not be empty")
    if channel not in CHANNELS:
        raise SystemExit(
            f"release_channel: unknown channel {channel!r}; "
            f"expected one of {', '.join(CHANNELS)}"
        )
    if channel == "nightly":
        return ["nightly"]
    if channel == "candidate":
        return [f"{value}-candidate", "candidate"]
    if is_prerelease(value):
        return [value]
    return [value, "latest"]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Decide release channel tags and prerelease status from a version string."
    )
    parser.add_argument("--version", required=True)
    parser.add_argument("--field", required=True, choices=["prerelease", "tags"])
    parser.add_argument("--channel", default="stable", choices=CHANNELS)
    args = parser.parse_args()

    if args.field == "prerelease":
        print("true" if is_prerelease(args.version) else "false")
    else:
        print(" ".join(channel_tags(args.version, args.channel)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
