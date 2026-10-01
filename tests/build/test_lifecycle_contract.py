"""NPM-03/09: the lifecycle contract's schemas stay closed, portable and in step with their document.

packages/cli/schemas/lifecycle-*.schema.json and operation-journal.schema.json are
read by two validators: packages/cli/src/lifecycle-contract.js (the coordinator)
and the native state utility (sub-plan 03 Task 3, Python's stdlib only). Both
interpret the same small JSON Schema subset, so this pins that subset, the regex
dialect both engines read identically, the canonical digest in Python, and the
tables specs/install/lifecycle-contract.md states in prose.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "packages" / "cli" / "schemas"
CONTRACT = ROOT / "specs" / "install" / "lifecycle-contract.md"
FIXTURES = ROOT / "packages" / "cli" / "test" / "fixtures" / "lifecycle"
EXIT_CODES_JS = ROOT / "packages" / "cli" / "src" / "exit-codes.js"
NAMES = ("lifecycle-plan", "lifecycle-event", "lifecycle-result", "operation-journal")

# The JSON Schema keywords both validators implement. Anything else in a schema
# would be ignored by one of them, so it is refused here instead.
KEYWORDS = {
    "$schema", "$id", "$ref", "$defs", "title", "description",
    "type", "const", "enum", "format", "pattern", "minLength", "maxLength", "minimum", "maximum",
    "properties", "required", "additionalProperties", "items", "minItems", "maxItems", "uniqueItems",
    "oneOf", "anyOf", "not",
}
FORMATS = {"cb-utc-timestamp", "cb-operation-id"}
TYPES = {"object", "array", "string", "integer", "boolean", "null"}
# Escapes and constructs whose meaning differs between ECMAScript and Python's re
# (Unicode classes, named groups, inline flags, lookbehind), plus $ anywhere but
# as an anchor: Python validators evaluate each pattern with $ read as \Z.
NONPORTABLE = re.compile(r"\\[dDwWsSbB]|\(\?<|\(\?[a-zA-Z]|\\\$|\[[^\]]*\$")
SECRET_NAME = re.compile(r"pass(word|wd)?|secret|token|credential|api_?key|private_key|vault_key|^key$")


def _schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))


def _nodes(node: Any, path: str = "#") -> Iterator[tuple[str, dict[str, Any]]]:
    """Every subschema in a schema document, with a JSON-pointer-ish location."""
    if not isinstance(node, dict):
        return
    yield path, node
    for key in ("properties", "$defs"):
        for name, child in node.get(key, {}).items():
            yield from _nodes(child, f"{path}/{key}/{name}")
    for key in ("items", "not"):
        if key in node:
            yield from _nodes(node[key], f"{path}/{key}")
    for key in ("oneOf", "anyOf"):
        for i, child in enumerate(node.get(key, [])):
            yield from _nodes(child, f"{path}/{key}/{i}")


def _python_pattern(pattern: str) -> re.Pattern[str]:
    """How a Python validator reads a contract pattern: $ means end of string."""
    return re.compile(pattern.replace("$", r"\Z"))


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _marked_table(marker: str) -> list[list[str]]:
    text = CONTRACT.read_text(encoding="utf-8")
    match = re.search(rf"<!-- {marker}:begin -->\n(.*?)<!-- {marker}:end -->", text, flags=re.DOTALL)
    assert match, f"specs/install/lifecycle-contract.md has no {marker} table"
    rows = [line for line in match.group(1).splitlines() if line.startswith("|")]
    cells = [[cell.strip().strip("`") for cell in row.strip("|").split("|")] for row in rows]
    return [row for row in cells[1:] if not set("".join(row)) <= {"-", " "}]


def _targets(cell: str) -> list[str]:
    return [] if cell == "—" else [part.strip().strip("`") for part in cell.split(",")]


def test_every_object_is_closed() -> None:
    for name in NAMES:
        for path, node in _nodes(_schema(name)):
            types = node.get("type", [])
            is_object = "properties" in node or "object" in ([types] if isinstance(types, str) else types)
            if is_object:
                assert node.get("additionalProperties") is False, f"{name}.schema.json {path} is not closed"
                assert set(node.get("required", [])) <= set(node.get("properties", {})), f"{name} {path}"


def test_every_document_is_version_one() -> None:
    for name in NAMES:
        schema = _schema(name)
        assert schema["properties"]["schema_version"] == {"const": 1}, name
        assert "schema_version" in schema["required"], name
        assert isinstance(schema["x-max-bytes"], int), name
    index = _schema("lifecycle-result")["$defs"]["history_index"]
    assert index["properties"]["schema_version"] == {"const": 1}
    assert isinstance(index["x-max-bytes"], int)


def test_schemas_use_only_the_shared_subset() -> None:
    for name in NAMES:
        for path, node in _nodes(_schema(name)):
            unknown = {k for k in node if k not in KEYWORDS and not k.startswith("x-")}
            assert not unknown, f"{name}.schema.json {path} uses {sorted(unknown)}"
            types = node.get("type", [])
            assert set([types] if isinstance(types, str) else types) <= TYPES, f"{name} {path}"
            if "format" in node:
                assert node["format"] in FORMATS, f"{name} {path}"
            if "$ref" in node:
                assert re.fullmatch(r"#/\$defs/[a-z_]+", node["$ref"]), f"{name} {path} refs outside its file"
                assert node["$ref"].rsplit("/", 1)[1] in _schema(name)["$defs"], f"{name} {path}"
            if "additionalProperties" in node:
                assert node["additionalProperties"] is False, f"{name} {path}"


def test_patterns_read_the_same_in_python() -> None:
    patterns = [
        (name, path, node["pattern"])
        for name in NAMES for path, node in _nodes(_schema(name)) if "pattern" in node
    ]
    assert len(patterns) > 10
    for name, path, pattern in patterns:
        assert not NONPORTABLE.search(pattern), f"{name} {path}: {pattern!r} is not portable"
        _python_pattern(pattern)
    defs = _schema("lifecycle-event")["$defs"]
    operation_id = _python_pattern(defs["operation_id"]["pattern"])
    assert operation_id.search("op-20260930-001")
    assert not operation_id.search("op-20260930-001\n"), "$ must not match before a trailing newline"
    absolute = _python_pattern(_schema("lifecycle-plan")["$defs"]["path"]["pattern"])
    for good in ("/", "/var/lib/circuitbreaker", "/srv/données/a b", "/srv/...", "/srv/.hidden"):
        assert absolute.search(good), good
    for bad in ("", "srv", "/srv/", "//srv", "/srv/../etc", "/srv/./x", "/..", "/srv\n", "/a\x1bb"):
        assert not absolute.search(bad), repr(bad)


def test_shared_definitions_are_identical_in_every_schema() -> None:
    seen: dict[str, tuple[str, Any]] = {}
    for name in NAMES:
        for def_name, definition in _schema(name).get("$defs", {}).items():
            if def_name in seen:
                first, value = seen[def_name]
                assert definition == value, f"$defs/{def_name} differs between {first} and {name}"
            else:
                seen[def_name] = (name, definition)
    for shared in ("operation_id", "digest", "timestamp", "version", "text", "error", "adapter", "state"):
        assert shared in seen, shared


def test_no_field_can_carry_a_secret_value() -> None:
    """Secrets are referenced through the recovery point, never carried (spec: "Keep
    secrets in protected recovery storage, outside logs and the journal")."""
    for name in NAMES:
        for path, node in _nodes(_schema(name)):
            for prop in node.get("properties", {}):
                assert prop == "key_id" or not SECRET_NAME.search(prop), f"{name} {path}: '{prop}'"


def test_transition_table_matches_the_contract_document() -> None:
    lifecycle = _schema("operation-journal")["x-lifecycle"]
    states = _schema("operation-journal")["$defs"]["state"]["enum"]
    rows = _marked_table("lifecycle-transitions")
    start = [row for row in rows if row[0] == "(start)"]
    assert start == [["(start)", lifecycle["initial"]["transaction"], lifecycle["initial"]["legacy"]]]
    table = {row[0]: (row[1], row[2]) for row in rows if row[0] != "(start)"}
    assert sorted(table) == sorted(states) and len(states) == 11
    for state in states:
        transaction, legacy = table[state]
        assert _targets(transaction) == lifecycle["transitions"]["transaction"][state], state
        assert _targets(legacy) == lifecycle["transitions"]["legacy"].get(state, []), state
    assert set(lifecycle["transitions"]["legacy"]) <= set(states)
    assert set(lifecycle["pre_mutation"]) == {"planned", "staged", "verified", "recovery_saved"}


def test_exit_codes_match_the_contract_document_and_the_cli() -> None:
    body = re.search(r"EXIT = Object\.freeze\(\{(.*?)\}\)", EXIT_CODES_JS.read_text(encoding="utf-8"), re.DOTALL)
    assert body
    cli = {name: int(code) for name, code in re.findall(r"([A-Z_]+): (\d+)", body.group(1))}
    documented = {row[1]: int(row[0]) for row in _marked_table("lifecycle-exit-codes")}
    assert documented == cli
    error_codes = _schema("lifecycle-result")["$defs"]["exit_name"]["enum"]
    assert set(error_codes) == set(cli) - {"OK"}


def test_canonical_vectors_serialize_identically_in_python() -> None:
    vectors = json.loads((FIXTURES / "digest-vectors.json").read_text(encoding="utf-8"))
    for vector in vectors["canonical"]:
        assert _canonical(vector["value"]) == vector["canonical"], vector["name"]


def test_plan_digest_vectors_agree_in_python() -> None:
    vectors = json.loads((FIXTURES / "digest-vectors.json").read_text(encoding="utf-8"))
    assert len(vectors["plans"]) >= 5
    for vector in vectors["plans"]:
        plan = {k: v for k, v in vector["plan"].items() if k not in ("plan_digest", "presentation")}
        canonical = _canonical(plan)
        assert canonical == vector["canonical"], vector["name"]
        digest = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        assert digest == vector["digest"], vector["name"]
        if "plan_digest" in vector["plan"]:
            assert vector["plan"]["plan_digest"] == digest, vector["name"]
