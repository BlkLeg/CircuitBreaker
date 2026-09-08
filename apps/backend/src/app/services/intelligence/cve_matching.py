"""Pure parsing and three-valued CVE applicability evaluation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from urllib.parse import unquote

Truth = Literal["true", "false", "unknown"]
VersionResult = Literal["match", "no_match", "unknown"]

_DOTTED_NUMERIC = re.compile(r"^v?\d+(?:[._-]\d+)*$")


@dataclass(frozen=True)
class NormalizedCVE:
    cve_id: str
    severity: str | None
    cvss_score: float | None
    summary: str | None
    published_at: datetime | None
    updated_at: datetime | None
    configurations: list[dict[str, Any]]


@dataclass(frozen=True)
class MatchEvidence:
    result: Truth
    evidence: list[dict[str, Any]] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)


def compare_versions(
    product_scheme: str | None, candidate: str | None, bound: str | None
) -> int | None:
    """Compare explicitly supported versions; return ``None`` when unknown."""
    if product_scheme != "dotted_numeric" or not candidate or not bound:
        return None
    if not _DOTTED_NUMERIC.fullmatch(candidate) or not _DOTTED_NUMERIC.fullmatch(bound):
        return None

    def parts(value: str) -> list[int]:
        return [int(part) for part in re.split(r"[._-]", value.removeprefix("v"))]

    left = parts(candidate)
    right = parts(bound)
    width = max(len(left), len(right))
    left.extend([0] * (width - len(left)))
    right.extend([0] * (width - len(right)))
    return (left > right) - (left < right)


def infer_version_scheme(version: str | None) -> str | None:
    return "dotted_numeric" if version and _DOTTED_NUMERIC.fullmatch(version) else None


def split_cpe23(criteria: str) -> list[str]:
    """Split a CPE 2.3 name while retaining escaped separators."""
    pieces: list[str] = []
    current: list[str] = []
    escaped = False
    for char in criteria:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ":":
            pieces.append(unquote("".join(current)))
            current = []
        else:
            current.append(char)
    current.append("\\" if escaped else "")
    pieces.append(unquote("".join(current)))
    return pieces


def parse_cpe(criteria: str) -> dict[str, str | None]:
    parts = split_cpe23(criteria)
    if len(parts) < 6 or parts[0] != "cpe" or parts[1] != "2.3":
        return {"part": None, "vendor": None, "product": None, "version": None}

    def value(index: int) -> str | None:
        raw = parts[index] if len(parts) > index else "*"
        return None if raw in {"", "*"} else raw

    return {"part": value(2), "vendor": value(3), "product": value(4), "version": value(5)}


def flatten_applicability(configurations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return every CPE match with a stable path for candidate indexing."""
    flattened: list[dict[str, Any]] = []

    def visit(node: dict[str, Any], path: str) -> None:
        for index, raw in enumerate(node.get("cpeMatch") or []):
            criteria = str(raw.get("criteria") or "")
            parsed = parse_cpe(criteria)
            flattened.append(
                {
                    "path": f"{path}.cpeMatch[{index}]",
                    "criteria": criteria,
                    "vulnerable": bool(raw.get("vulnerable", True)),
                    **parsed,
                    "version_start_including": raw.get("versionStartIncluding"),
                    "version_start_excluding": raw.get("versionStartExcluding"),
                    "version_end_including": raw.get("versionEndIncluding"),
                    "version_end_excluding": raw.get("versionEndExcluding"),
                }
            )
        for index, child in enumerate(node.get("children") or []):
            if isinstance(child, dict):
                visit(child, f"{path}.children[{index}]")

    for config_index, config in enumerate(configurations):
        for node_index, node in enumerate(config.get("nodes") or []):
            if isinstance(node, dict):
                visit(node, f"configurations[{config_index}].nodes[{node_index}]")
    return flattened


def _combine(values: list[Truth], operator: str) -> Truth:
    if not values:
        return "unknown"
    if operator == "AND":
        if "false" in values:
            return "false"
        return "unknown" if "unknown" in values else "true"
    if "true" in values:
        return "true"
    return "unknown" if "unknown" in values else "false"


def _version_result(
    match: dict[str, Any], identity: dict[str, Any]
) -> tuple[VersionResult, str | None]:
    candidate = identity.get("version")
    scheme = identity.get("version_scheme")
    exact = parse_cpe(str(match.get("criteria") or "")).get("version")
    bounds = {
        "versionStartIncluding": (match.get("versionStartIncluding"), 0, 0),
        "versionStartExcluding": (match.get("versionStartExcluding"), 0, 1),
        "versionEndIncluding": (match.get("versionEndIncluding"), 1, 0),
        "versionEndExcluding": (match.get("versionEndExcluding"), 1, 1),
    }
    if exact and exact != "-":
        comparison = compare_versions(scheme, candidate, exact)
        if comparison is None:
            return "unknown", "version_unsupported"
        return ("match", None) if comparison == 0 else ("no_match", None)
    if not any(bound for bound, _, _ in bounds.values()):
        return "match", None
    if not candidate:
        return "unknown", "version_missing"
    for bound, side, exclusive in bounds.values():
        if not bound:
            continue
        comparison = compare_versions(scheme, candidate, str(bound))
        if comparison is None:
            return "unknown", "version_unsupported"
        if side == 0 and (comparison < 0 or (exclusive and comparison == 0)):
            return "no_match", None
        if side == 1 and (comparison > 0 or (exclusive and comparison == 0)):
            return "no_match", None
    return "match", None


def _evaluate_cpe(match: dict[str, Any], identity: dict[str, Any]) -> MatchEvidence:
    parsed = parse_cpe(str(match.get("criteria") or ""))
    vendor = (identity.get("vendor") or "").casefold()
    product = (identity.get("product") or "").casefold()
    cpe_vendor = (parsed.get("vendor") or "").casefold()
    cpe_product = (parsed.get("product") or "").casefold()
    same_product = (not cpe_vendor or cpe_vendor == vendor) and (
        not cpe_product or cpe_product == product
    )
    vulnerable = bool(match.get("vulnerable", True))
    if not same_product:
        result: Truth = "false" if vulnerable else "unknown"
        reason = None if vulnerable else "environment_prerequisite_unknown"
        return MatchEvidence(
            result,
            [
                {
                    "criteria": str(match.get("criteria") or ""),
                    "vendor": parsed.get("vendor"),
                    "product": parsed.get("product"),
                    "vulnerable": vulnerable,
                    "version_result": "no_match" if vulnerable else "unknown",
                    "reason": reason,
                }
            ],
            [reason] if reason else [],
        )
    version_result, reason = _version_result(match, identity)
    if version_result == "match":
        truth_result: Truth = "true"
    elif version_result == "no_match":
        truth_result = "false"
    else:
        truth_result = "unknown"
    return MatchEvidence(
        truth_result,
        [
            {
                "criteria": str(match.get("criteria") or ""),
                "vendor": parsed.get("vendor"),
                "product": parsed.get("product"),
                "vulnerable": vulnerable,
                "version_result": version_result,
                "reason": reason,
            }
        ],
        [reason] if reason else [],
    )


def _evaluate_node(node: dict[str, Any], identity: dict[str, Any]) -> MatchEvidence:
    parts = [_evaluate_cpe(item, identity) for item in node.get("cpeMatch") or []]
    parts.extend(
        _evaluate_node(child, identity)
        for child in node.get("children") or []
        if isinstance(child, dict)
    )
    result = _combine([part.result for part in parts], str(node.get("operator") or "OR").upper())
    if node.get("negate"):
        result = {"true": "false", "false": "true", "unknown": "unknown"}[result]  # type: ignore[assignment]
    return MatchEvidence(
        result,
        [entry for part in parts for entry in part.evidence],
        sorted({item for part in parts for item in part.limitations}),
    )


def evaluate_applicability(
    configuration: list[dict[str, Any]],
    identity: dict[str, Any],
    environment: dict[str, Any] | None = None,
) -> MatchEvidence:
    """Evaluate NVD configuration trees without collapsing unknown to false."""
    del environment  # Reserved for a future explicit environment identity contract.
    results: list[MatchEvidence] = []
    for config in configuration:
        nodes = [
            _evaluate_node(node, identity)
            for node in config.get("nodes") or []
            if isinstance(node, dict)
        ]
        results.append(
            MatchEvidence(
                _combine([node.result for node in nodes], str(config.get("operator") or "OR")),
                [entry for node in nodes for entry in node.evidence],
                sorted({item for node in nodes for item in node.limitations}),
            )
        )
    return MatchEvidence(
        _combine([result.result for result in results], "OR"),
        [entry for result in results for entry in result.evidence],
        sorted({item for result in results for item in result.limitations}),
    )
