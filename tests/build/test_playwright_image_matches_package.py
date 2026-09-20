"""The pinned Playwright container and `@playwright/test` must name one version.

CI runs the browser suite inside `mcr.microsoft.com/playwright:vX.Y.Z-noble`,
whose `/ms-playwright` browsers are built for exactly that release. The npm
package decides which browser build Playwright then looks for. Move one without
the other and every spec dies before it asserts anything:

    Error: browserType.launch: Executable doesn't exist at
      /ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/...

That is not a visual diff or a flake, though it reads as one: visual,
accessibility and content specs all fail together, because none of them ever
got a browser. It happened when a Dependabot dev-group bump moved
`@playwright/test` 1.62.1 -> 1.63.0 and left the image on v1.62.1-noble.

`make verify` does NOT run the browser suite, so nothing local catches this.
This test does, in the repo-policy suite that Tier 0 always runs.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_JSON = ROOT / "apps" / "frontend" / "package.json"
WORKFLOWS = ROOT / ".github" / "workflows"

_IMAGE = re.compile(r"mcr\.microsoft\.com/playwright:v(?P<version>\d+\.\d+\.\d+)-\w+")


def _declared_version() -> str:
    manifest = json.loads(PACKAGE_JSON.read_text())
    deps = {**manifest.get("dependencies", {}), **manifest.get("devDependencies", {})}
    spec = deps.get("@playwright/test")
    assert spec, "@playwright/test is not declared in apps/frontend/package.json"
    # "^1.63.0" -> "1.63.0"; the image tag has no range syntax to match against.
    return spec.lstrip("^~>=< ")


def _pinned_images() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for workflow in sorted(WORKFLOWS.glob("*.yml")):
        versions = {m.group("version") for m in _IMAGE.finditer(workflow.read_text())}
        if versions:
            found[workflow.name] = versions
    return found


def test_playwright_image_is_pinned_somewhere():
    """Guards the guard: a renamed image would make the check below vacuous."""
    assert _pinned_images(), (
        "no workflow pins mcr.microsoft.com/playwright:<version> any more — either the "
        "browser suite stopped running in that container, or this test's regex is stale"
    )


def test_playwright_image_matches_the_declared_package_version():
    declared = _declared_version()
    mismatched = {
        name: sorted(versions)
        for name, versions in _pinned_images().items()
        if versions != {declared}
    }
    assert not mismatched, (
        f"@playwright/test is {declared} but the pinned container(s) disagree: "
        f"{mismatched}. The image's bundled browsers are built per release, so a "
        "mismatch fails every browser spec at launch. Move both together."
    )
