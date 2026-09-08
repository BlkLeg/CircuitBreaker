#!/usr/bin/env python3
"""Refetch the self-hosted UI fonts and regenerate their @font-face stylesheet.

The UI used to load its typeface from fonts.googleapis.com at runtime. That is
wrong for this project twice over: `CB_AIRGAP` is a first-class mode and an
air-gapped install silently fell back to system fonts, and a self-hosted tool
should not disclose every viewer to a third party. The faces are vendored under
`apps/frontend/public/fonts` instead.

Run this only to add a family or refresh the files — it needs the internet, and
the fonts it writes are committed so that builds, air-gapped installs and the
visual-baseline suite never do.

    python3 scripts/fetch-ui-fonts.py

Only the latin and latin-ext subsets are kept. The UI is English; carrying
Cyrillic, Greek and Vietnamese would roughly triple the vendored size for text
this app never renders. Add a subset here if that stops being true.

Every family is SIL Open Font License 1.1; the per-family licence text is
fetched alongside the fonts into `public/fonts/licenses/`.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FONT_DIR = REPO_ROOT / "apps/frontend/public/fonts"
LICENSE_DIR = FONT_DIR / "licenses"
STYLESHEET = REPO_ROOT / "apps/frontend/src/styles/fonts.css"

# A desktop UA, or Google serves the ttf fallback stylesheet instead of woff2.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

KEEP_SUBSETS = {"latin", "latin-ext"}

# (family as Google names it, file prefix, google/fonts ofl slug, weights)
FAMILIES = [
    ("Inter", "Inter", "inter", [400, 500, 600]),
    ("JetBrains Mono", "JetBrainsMono", "jetbrainsmono", [400, 500]),
    ("Fira Sans", "FiraSans", "firasans", [400, 500, 600]),
    ("IBM Plex Sans", "IBMPlexSans", "ibmplexsans", [400, 500, 600]),
    ("Nunito", "Nunito", "nunito", [400, 600, 700]),
    ("Roboto", "Roboto", "roboto", [400, 500, 700]),
    ("Source Code Pro", "SourceCodePro", "sourcecodepro", [400, 500]),
]


def _curl(url: str, *, headers: dict[str, str] | None = None) -> bytes:
    cmd = ["curl", "-sSfL", "--max-time", "60"]
    for key, value in (headers or {}).items():
        cmd += ["-H", f"{key}: {value}"]
    cmd.append(url)
    return subprocess.run(cmd, capture_output=True, check=True).stdout


def fetch_family(label: str, prefix: str, slug: str, weights: list[int]) -> list[dict]:
    """Downloads one family's woff2 files and returns its @font-face records."""
    query = label.replace(" ", "+")
    url = (
        f"https://fonts.googleapis.com/css2?family={query}"
        f":wght@{';'.join(str(w) for w in weights)}&display=swap"
    )
    css = _curl(url, headers={"User-Agent": USER_AGENT}).decode()

    faces: list[dict] = []
    for subset, block in re.findall(
        r"/\* ([a-z-]+) \*/\s*(@font-face \{.*?\})", css, re.DOTALL
    ):
        if subset not in KEEP_SUBSETS:
            continue
        weight = re.search(r"font-weight:\s*(\d+)", block).group(1)
        style = re.search(r"font-style:\s*(\w+)", block).group(1)
        source = re.search(r"url\((https://[^)]+\.woff2)\)", block).group(1)
        unicode_range = re.search(r"unicode-range:\s*([^;]+);", block).group(1).strip()

        filename = f"{prefix}-{weight}-{subset}.woff2"
        (FONT_DIR / filename).write_bytes(_curl(source))
        faces.append(
            {
                "family": label,
                "weight": weight,
                "style": style,
                "file": filename,
                "range": unicode_range,
            }
        )

    licence = _curl(
        f"https://raw.githubusercontent.com/google/fonts/main/ofl/{slug}/OFL.txt"
    )
    (LICENSE_DIR / f"{slug}-OFL.txt").write_bytes(licence)
    return faces


def render_stylesheet(faces: list[dict]) -> str:
    by_family: dict[str, list[dict]] = {}
    for face in faces:
        by_family.setdefault(face["family"], []).append(face)

    out = [
        "/**",
        " * Self-hosted UI fonts.",
        " *",
        " * The app used to inject a <link> to fonts.googleapis.com for whichever family",
        " * the user had selected, which meant every page load reached a third party.",
        " * That is wrong twice over here: air-gap is a first-class mode in this project",
        " * (`CB_AIRGAP`), and an air-gapped install silently fell back to system fonts",
        " * while the weather widget beside it correctly stood down; and it disclosed",
        " * every viewer's IP to Google on a page they self-host precisely to avoid that.",
        " *",
        " * These are the same families, latin and latin-ext subsets, served from",
        " * /fonts. Declaring a face costs nothing until it is used: the browser fetches",
        " * only the family actually selected, and only the unicode ranges its text",
        " * needs. All seven are SIL Open Font License 1.1 — see fonts/licenses/.",
        " *",
        " * Generated by scripts/fetch-ui-fonts.py — do not edit by hand.",
        " */",
        "",
    ]
    for family, items in by_family.items():
        out.append(f"/* {family} */")
        for face in sorted(items, key=lambda f: (f["weight"], f["file"])):
            out += [
                "@font-face {",
                f"  font-family: '{family}';",
                f"  font-style: {face['style']};",
                f"  font-weight: {face['weight']};",
                "  font-display: swap;",
                f"  src: url('/fonts/{face['file']}') format('woff2');",
                f"  unicode-range: {face['range']};",
                "}",
            ]
        out.append("")
    return "\n".join(out)


def main() -> None:
    FONT_DIR.mkdir(parents=True, exist_ok=True)
    LICENSE_DIR.mkdir(parents=True, exist_ok=True)

    faces: list[dict] = []
    for label, prefix, slug, weights in FAMILIES:
        family_faces = fetch_family(label, prefix, slug, weights)
        print(f"{label}: {len(family_faces)} face(s)")
        faces += family_faces

    STYLESHEET.write_text(render_stylesheet(faces), encoding="utf-8")
    print(f"\n{len(faces)} faces -> {STYLESHEET.relative_to(REPO_ROOT)}")
    print(json.dumps({"families": len(FAMILIES), "faces": len(faces)}))


if __name__ == "__main__":
    main()
