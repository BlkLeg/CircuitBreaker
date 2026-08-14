"""Validate SEC-18 scanner suppression metadata."""

from __future__ import annotations

import argparse
import json
import tomllib
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "specs/1.0.0/release-control/security-suppressions.json"
TRIVY_IGNORE = ROOT / ".trivyignore"
GITLEAKS_IGNORE = ROOT / ".gitleaksignore"
GITLEAKS_CONFIG = ROOT / ".gitleaks.toml"

REQUIRED_FIELDS = {
    "id",
    "tool",
    "selector",
    "owner",
    "reviewer",
    "reason",
    "compensating_control",
    "expiry",
    "requirements",
}


def _fail(message: str) -> None:
    raise SystemExit(f"security suppression validation failed: {message}")


def _load_manifest(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        _fail(f"missing manifest: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("suppressions")
    if not isinstance(rows, list):
        _fail("manifest must contain a suppressions list")
    return rows


def _ignore_entries(path: Path) -> set[str]:
    if not path.exists():
        return set()
    entries: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        entries.add(line)
    return entries


def _gitleaks_config_allowlist_ids(path: Path) -> set[str]:
    """Return the `id` of every `[[allowlists]]` block in `.gitleaks.toml`.

    A config allowlist suppresses findings exactly like a `.gitleaksignore`
    entry does, but broader — it is path-pattern based, so one block can silence
    a whole tree. Validating only the ignore files left these outside the
    governance the ignore files are subject to.
    """
    if not path.exists():
        return set()
    config = tomllib.loads(path.read_text(encoding="utf-8"))
    blocks = config.get("allowlists")
    if not isinstance(blocks, list):
        return set()
    ids: set[str] = set()
    for index, block in enumerate(blocks, start=1):
        block_id = block.get("id") if isinstance(block, dict) else None
        if not block_id:
            # An unnamed block cannot be tied to an owner or an expiry.
            _fail(f"{path.name} allowlist #{index} has no `id` to govern it by")
        ids.add(str(block_id))
    return ids


def validate(path: Path, today: date) -> None:
    rows = _load_manifest(path)
    seen: set[str] = set()
    by_tool: dict[str, set[str]] = {}

    for index, row in enumerate(rows, start=1):
        missing = [field for field in sorted(REQUIRED_FIELDS) if not row.get(field)]
        if missing:
            _fail(f"row {index} missing required fields: {', '.join(missing)}")
        suppression_id = str(row["id"])
        if suppression_id in seen:
            _fail(f"duplicate suppression id: {suppression_id}")
        seen.add(suppression_id)

        try:
            expiry = date.fromisoformat(str(row["expiry"]))
        except ValueError as exc:
            raise SystemExit(f"row {index} has invalid expiry: {row['expiry']}") from exc
        if expiry < today:
            _fail(f"{suppression_id} expired on {expiry.isoformat()}")

        requirements = row["requirements"]
        if not isinstance(requirements, list) or not {"SEC-18", "RC-08"} <= set(requirements):
            _fail(f"{suppression_id} must reference SEC-18 and RC-08")
        by_tool.setdefault(str(row["tool"]), set()).add(str(row["selector"]))

    trivy_manifest = by_tool.get("trivy", set())
    missing_trivy = _ignore_entries(TRIVY_IGNORE) - trivy_manifest
    if missing_trivy:
        _fail(f".trivyignore entries missing manifest metadata: {sorted(missing_trivy)}")

    gitleaks_entries = _ignore_entries(GITLEAKS_IGNORE)
    gitleaks_manifest = by_tool.get("gitleaks", set())
    missing_gitleaks = {
        entry
        for entry in gitleaks_entries
        if not any(selector in entry for selector in gitleaks_manifest)
    }
    if missing_gitleaks:
        _fail(f".gitleaksignore entries missing manifest metadata: {sorted(missing_gitleaks)}")

    config_manifest = by_tool.get("gitleaks-config", set())
    missing_config = _gitleaks_config_allowlist_ids(GITLEAKS_CONFIG) - config_manifest
    if missing_config:
        _fail(f".gitleaks.toml allowlists missing manifest metadata: {sorted(missing_config)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--today", type=date.fromisoformat, default=datetime.now(UTC).date())
    args = parser.parse_args()
    validate(args.manifest, args.today)
    print(f"security suppression metadata valid: {args.manifest}")


if __name__ == "__main__":
    main()
