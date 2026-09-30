"""RISK-009 / ADR 0006: npm is not a Circuit Breaker distribution channel *yet*.

ADR 0006 (2026-09-30, superseding ADR 0004) puts an npm installer CLI on the road
to 1.0, and keeps ADR 0004's surface rules in force until that package ships and
passes its NPM gates. This suite enforces those interim rules and is revised
deliberately in the same change that first publishes the CLI.

ADR 0004 decides that no Circuit Breaker package is published to npm for the
1.0 line, and its Consequences add that documentation and release notes "must
not show `npm install` or `npx` as an installation path". Until this file, only
the first half of that had a test behind it
(test_tracked_file_policy.py::test_root_npm_manifest_stays_private, which
covers the root manifest alone). The rest was a sentence in an ADR.

This suite makes the remaining promises mechanical:

* every tracked ``package.json`` is ``private: true`` — the frontend workspace
  as well as the root — so ``npm publish`` refuses from any directory;
* no workflow publishes to an npm registry;
* no user-facing installation surface (README, CHANGELOG, every page in the
  MkDocs nav, docs/installation/, docs/release/, docs/updates/, install.sh,
  and any release-notes file a workflow feeds to ``gh release``) presents a
  package-manager install or exec of a Circuit Breaker package; and
* the installation pages carry no package-manager command at all.

The matcher is deliberately narrow in the second-to-last rule. Developer
documentation legitimately says ``npm install -D @playwright/test``,
``npm ci`` or ``cd apps/frontend && npx playwright test``; those install the
project's *dependencies*, not Circuit Breaker. What the ADR forbids is
installing or running *Circuit Breaker itself* through npm, so a hit needs both
an install/exec command and a Circuit Breaker package name in that command's
own arguments. The self-check tests at the bottom pin both directions.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADR = ROOT / "docs" / "adr" / "0006-npm-installer-cli-for-1.0.md"
MKDOCS = ROOT / "mkdocs.yml"
SUPPORT_CONTRACT = ROOT / "docs" / "release" / "1.0.0-support-contract.md"
INSTALL_INDEX = ROOT / "docs" / "installation" / "index.md"
WORKFLOWS = ROOT / ".github" / "workflows"

# Directories whose every Markdown page is a user-facing installation or
# release surface, whether or not the nav lists it.
SURFACE_DIRS = ("docs/installation/", "docs/release/", "docs/updates/")
# Individual tracked files that users read to install or upgrade.
SURFACE_FILES = ("README.md", "CHANGELOG.md", "install.sh")

# A package-manager command that installs or executes a package. `npm ci` and
# `npm run` are absent on purpose: neither can fetch a named package, so
# neither can be an installation path for one.
INSTALL_OR_EXEC = re.compile(
    r"\b(?:"
    r"npx|pnpx|bunx"
    r"|npm\s+(?:install|isntall|i|in|add|exec|x)"
    r"|pnpm\s+(?:add|install|i|dlx|exec)"
    r"|yarn\s+(?:global\s+add|add|dlx)"
    r"|bun\s+(?:add|install|i|x)"
    r")\b",
    re.IGNORECASE,
)

# The arguments of one command end at a shell separator, a Markdown code-span
# delimiter, or the end of the line. Anything past that belongs to a different
# command or to prose, and must not be attributed to this one.
ARGUMENT_END = re.compile(r"&&|\|\||[;|`\n)]")
ARGUMENT_SPAN_LIMIT = 120

# A Circuit Breaker package name as an argument: anything in the @blkleg scope
# or under the BlkLeg GitHub owner, or the bare product name. The bare name
# must stand alone — not the tail of a path (`/opt/circuitbreaker`), not a file
# name (`circuitbreaker.test.js`) — so a dependency command that merely runs
# inside the project tree is not mistaken for installing the project.
CB_PACKAGE = re.compile(
    r"@blkleg/"
    r"|\bblkleg/"
    r"|(?<![\w/.@-])circuit[-_]?breaker(?![\w-]|\.[a-z])",
    re.IGNORECASE,
)

# Any package-manager command at all. Used only on installation pages, where
# even a dependency command would read as a step in installing Circuit Breaker.
ANY_PACKAGE_MANAGER_COMMAND = re.compile(
    r"\b(?:npx|pnpx|bunx)\s+[-@\w]"
    r"|\b(?:npm|pnpm|yarn|bun)\s+"
    r"(?:install|isntall|i|in|ci|add|exec|x|dlx|run|start|link|global|publish|create|init)\b",
    re.IGNORECASE,
)

NPM_PUBLISH = re.compile(
    r"\b(?:npm|pnpm|yarn(?:\s+npm)?|bun)\s+publish\b"
    r"|npm-publish"
    r"|\bNPM_TOKEN\b"
    r"|\bNODE_AUTH_TOKEN\b",
    re.IGNORECASE,
)


def tracked_files() -> list[str]:
    """Every path in the git index, repo-root-relative."""
    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    )
    return out.stdout.splitlines()


def cb_install_instructions(text: str) -> list[str]:
    """Return each package-manager command in ``text`` that installs or runs Circuit Breaker."""
    hits: list[str] = []
    for command in INSTALL_OR_EXEC.finditer(text):
        rest = text[command.end() : command.end() + ARGUMENT_SPAN_LIMIT]
        end = ARGUMENT_END.search(rest)
        arguments = rest[: end.start()] if end else rest
        if CB_PACKAGE.search(arguments):
            hits.append((command.group(0) + arguments).strip())
    return hits


def mkdocs_nav_pages() -> list[str]:
    """Every Markdown page the MkDocs nav publishes, as docs/-prefixed paths.

    Parsed with a line pattern rather than a YAML loader so the suite needs no
    third-party package; the nav is a plain list of ``- Title: page.md`` rows.
    """
    text = MKDOCS.read_text(encoding="utf-8")
    nav = re.search(r"^nav:\n((?:[ \t]+.*\n|\n)+)", text, re.MULTILINE)
    assert nav, "mkdocs.yml has no top-level nav: block"
    pages = re.findall(
        r"^\s+-\s+(?:[^:\n]+:\s*)?(\S+\.md)\s*$", nav.group(1), re.MULTILINE
    )
    return [f"docs/{page}" for page in pages]


def release_notes_files() -> list[str]:
    """Files any workflow hands to a release as its notes body."""
    found: list[str] = []
    for workflow in sorted(WORKFLOWS.glob("*.y*ml")):
        text = workflow.read_text(encoding="utf-8")
        found += re.findall(r"(?:--notes-file|body_path:)\s*[\"']?([\w./-]+)", text)
    return found


def installation_surfaces() -> list[str]:
    """Tracked, user-facing files that must never show npm as an install path."""
    tracked = set(tracked_files())
    candidates = (
        set(SURFACE_FILES) | set(mkdocs_nav_pages()) | set(release_notes_files())
    )
    candidates |= {
        path
        for path in tracked
        if path.startswith(SURFACE_DIRS) and path.endswith(".md")
    }
    return sorted(candidates & tracked)


def test_every_tracked_package_manifest_is_private() -> None:
    """NPM-02, extended past the root: no workspace can be `npm publish`ed."""
    manifests = [p for p in tracked_files() if Path(p).name == "package.json"]
    assert "apps/frontend/package.json" in manifests, (
        "the frontend manifest is no longer tracked where this test expects it; "
        "update the test rather than letting it pass over nothing"
    )
    offenders = []
    for path in manifests:
        manifest = json.loads((ROOT / path).read_text(encoding="utf-8"))
        if manifest.get("private") is not True or "publishConfig" in manifest:
            offenders.append(path)
    assert not offenders, (
        f"{offenders} can be published to npm. ADR 0004 decides no Circuit "
        'Breaker package is published for 1.0: set "private": true and drop '
        "any publishConfig."
    )


def test_no_workflow_publishes_to_npm() -> None:
    """ADR 0004 decision 2: nothing is published to npmjs under any name."""
    offenders = []
    for workflow in sorted(WORKFLOWS.glob("*.y*ml")):
        for number, line in enumerate(
            workflow.read_text(encoding="utf-8").splitlines(), 1
        ):
            if line.lstrip().startswith("#"):
                continue
            if NPM_PUBLISH.search(line):
                offenders.append(
                    f"{workflow.relative_to(ROOT)}:{number}: {line.strip()}"
                )
    assert not offenders, (
        "a workflow publishes to an npm registry or carries an npm publish "
        f"credential, which ADR 0004 rules out for 1.0: {offenders}"
    )


def test_surfaces_are_actually_collected() -> None:
    """Guard against the scan below passing vacuously over an empty list."""
    surfaces = installation_surfaces()
    for required in (
        "README.md",
        "CHANGELOG.md",
        "docs/installation/index.md",
        "docs/installation/quick-install.md",
        "docs/release/1.0.0-support-contract.md",
    ):
        assert required in surfaces, f"{required} dropped out of the scanned surfaces"
    assert len(mkdocs_nav_pages()) >= 20, "mkdocs nav parsing found almost no pages"


def test_no_surface_presents_npm_as_an_install_path() -> None:
    """ADR 0004 Consequences: docs and release notes show no npm/npx install."""
    offenders = []
    for path in installation_surfaces():
        text = (ROOT / path).read_text(encoding="utf-8")
        offenders += [f"{path}: {hit}" for hit in cb_install_instructions(text)]
    assert not offenders, (
        "these user-facing pages present a package manager as a way to install "
        "or run Circuit Breaker, which ADR 0004 declines for 1.0 — native "
        f"(install.sh / packages) and the mono image are the only channels: {offenders}"
    )


def test_installation_pages_carry_no_package_manager_commands() -> None:
    """On an install page, any npm command reads as an installation step."""
    offenders = []
    for path in installation_surfaces():
        if not path.startswith("docs/installation/"):
            continue
        text = (ROOT / path).read_text(encoding="utf-8")
        offenders += [
            f"{path}: {m.group(0)}" for m in ANY_PACKAGE_MANAGER_COMMAND.finditer(text)
        ]
    assert not offenders, (
        "installation pages must not carry package-manager commands; move "
        f"developer setup to CONTRIBUTING.md: {offenders}"
    )


def test_support_contract_does_not_offer_npm() -> None:
    rows = [
        line
        for line in SUPPORT_CONTRACT.read_text(encoding="utf-8").splitlines()
        if line.startswith("|") and "npm" in line.lower()
    ]
    assert rows, "the support contract no longer has an npm row at all"
    for row in rows:
        status = row.split("|")[2].strip().lower()
        assert "supported" not in status, f"npm is listed as supported: {row}"
        assert "0006-npm-installer-cli-for-1.0.md" in row, (
            f"the npm row does not cite ADR 0006: {row}"
        )


def test_installation_overview_says_npm_is_not_a_channel() -> None:
    text = INSTALL_INDEX.read_text(encoding="utf-8")
    assert "0006-npm-installer-cli-for-1.0.md" in text, (
        "docs/installation/index.md does not point at ADR 0006"
    )
    assert re.search(r"npm is not an installation channel", text, re.IGNORECASE), (
        "docs/installation/index.md no longer states that npm is not a channel"
    )


def test_adr_still_carries_the_rule_this_file_enforces() -> None:
    text = ADR.read_text(encoding="utf-8")
    assert "must not show `npm install` or `npx` as an installation path" in text, (
        "ADR 0006's interim docs rule changed; revisit this suite rather than "
        "enforcing a rule the ADR no longer states"
    )


# ---------------------------------------------------------------------------
# Matcher self-checks. Each fixture is one line as it might appear in docs.
# ---------------------------------------------------------------------------

CB_INSTALLS = [
    "npm install circuitbreaker",
    "npm i -g circuitbreaker",
    "npm install --global circuit_breaker",
    "npm isntall circuit-breaker",
    "Run `npx @blkleg/circuitbreaker` to get started.",
    "npx circuit-breaker install",
    "npx --yes @BlkLeg/CircuitBreaker@1.0.0",
    "NPX CIRCUITBREAKER",
    "npm exec --yes -- circuitbreaker",
    "npm install github:BlkLeg/circuitbreaker",
    "npm i https://github.com/BlkLeg/circuitbreaker",
    "pnpm add @blkleg/cb-agent",
    "pnpm dlx circuitbreaker",
    "yarn global add circuitbreaker",
    "yarn dlx @blkleg/circuitbreaker",
    "bunx circuitbreaker",
    "bun add circuitbreaker",
    "sudo npm install -g circuitbreaker && circuitbreaker start",
]

NOT_CB_INSTALLS = [
    "npm install -D @playwright/test",
    "npx playwright install chromium firefox webkit",
    "cd apps/frontend && npx playwright test",
    "npm ci",
    "npm install --prefix apps/frontend",
    "cd /opt/circuitbreaker && npm ci",
    "npm install --prefix /opt/circuitbreaker/frontend",
    "npx vitest run src/__tests__/circuitbreaker.test.js",
    "Run `npm install` once at the repo root, then open Circuit Breaker.",
    "npx lint-staged --concurrent false",
    "npm run build && circuit-breaker --selftest",
    "No Circuit Breaker package is published to npm.",
    "curl -fsSL https://example.invalid/install.sh | bash",
    "docker pull ghcr.io/blkleg/circuitbreaker:latest",
    "circuit-breaker --version",
]


def test_matcher_flags_every_cb_install() -> None:
    missed = [line for line in CB_INSTALLS if not cb_install_instructions(line)]
    assert not missed, f"matcher misses Circuit Breaker installs: {missed}"


def test_matcher_ignores_dependency_commands_and_prose() -> None:
    flagged = {line: cb_install_instructions(line) for line in NOT_CB_INSTALLS}
    flagged = {line: hits for line, hits in flagged.items() if hits}
    assert not flagged, f"matcher flags legitimate developer commands: {flagged}"


def test_strict_install_page_matcher_both_ways() -> None:
    for line in ("npm ci", "cd apps/frontend && npx playwright test", "yarn install"):
        assert ANY_PACKAGE_MANAGER_COMMAND.search(line), line
    for line in (
        "No Circuit Breaker package is published to npm, and none is planned.",
        "The frontend's `package.json` is marked private.",
        "Install with install.sh",
    ):
        assert not ANY_PACKAGE_MANAGER_COMMAND.search(line), line


def test_publish_matcher_both_ways() -> None:
    for line in (
        "run: npm publish --access public",
        "run: pnpm publish",
        "run: yarn npm publish",
        "uses: JS-DevTools/npm-publish@v3",
        "NODE_AUTH_TOKEN: ${{ secrets.NPM_TOKEN }}",
    ):
        assert NPM_PUBLISH.search(line), line
    for line in ("run: npm ci", "run: npx playwright test", "name: Publish :nightly"):
        assert not NPM_PUBLISH.search(line), line
