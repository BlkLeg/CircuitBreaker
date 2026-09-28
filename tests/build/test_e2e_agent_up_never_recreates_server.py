"""Every composed-E2E `compose up` of an agent service must pass `--no-deps`.

`cb-agent` and `cb-agent-2` declare `depends_on: [circuitbreaker]` in
`apps/agent/e2e/docker-compose.yml`. Without `--no-deps`, compose v2 treats
`docker compose up -d cb-agent` as a request to converge the dependency too,
and recreates the already-running server whenever it judges the container out
of date. That kills every connection the test opened against the old
container. In `test_agent_full_lifecycle_enroll_through_revoke_and_reconnect`
it killed the `/agents/stream` listener `_enroll_agent` had opened, so step 9
waited for a `revoked` push on a dead socket and failed with "no close frame".
The stderr showed `Container circuitbreaker Recreate/Recreated` right after
`cb-agent Built`, and the server's `started_at` moved with `restart_count` 0.

`_enroll_agent` already used `--no-deps` for `compose run` and documented why.
The `up -d` calls never got the same fix. This guard makes that a build
failure instead of a composed-E2E failure 40 minutes into CI.

The service a site starts is often a variable, such as a helper's parameter or
`*services`. So each name is resolved through the helper's call sites and
defaults back to the literal or module constant it came from. A name that
cannot be resolved counts as an agent service, so the guard fails closed.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
E2E_DIR = ROOT / "apps" / "agent" / "e2e"
TEST_FILE = E2E_DIR / "test_agent_e2e.py"
COMPOSE_FILE = E2E_DIR / "docker-compose.yml"

SERVER_SERVICE = "circuitbreaker"

#: Where an agent service is started after the server is up, counted at the
#: call site where the service name originates: 17 direct starts plus
#: `_rewind_spool_head`'s restart of the SIGKILLed agent. A refactor may move
#: the flag into a helper; it must not make these sites invisible to the guard.
MIN_AGENT_UP_SITES = 18

_UNRESOLVED = "<unresolved>"


@dataclass(frozen=True)
class _Origin:
    """One service name reaching a `compose up`, and the line it came from."""

    line: int
    service: str


def _agent_services() -> frozenset[str]:
    """Services that depend on the server, so a bare `up` may recreate it."""
    compose = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    agents: set[str] = set()
    for name, spec in compose["services"].items():
        depends_on = spec.get("depends_on") or []
        # Short form is a list of names; long form is a mapping keyed by name.
        if SERVER_SERVICE in depends_on:
            agents.add(name)
    return frozenset(agents)


class _Resolver:
    """Resolves the service arguments of `compose up` lists back to literals."""

    def __init__(self, tree: ast.Module) -> None:
        self.constants: dict[str, str] = {}
        for node in tree.body:
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                self.constants[node.targets[0].id] = node.value.value
        self.calls: dict[str, list[ast.Call]] = {}
        self.enclosing: dict[int, ast.FunctionDef] = {}
        for walked in ast.walk(tree):
            if isinstance(walked, ast.FunctionDef):
                for child in ast.walk(walked):
                    # Innermost wins: ast.walk visits outer functions first.
                    self.enclosing[id(child)] = walked
            if isinstance(walked, ast.Call) and isinstance(walked.func, ast.Name):
                self.calls.setdefault(walked.func.id, []).append(walked)

    def expr(self, node: ast.expr, line: int, depth: int = 0) -> list[_Origin]:
        """Every string *node* can evaluate to, tagged with its origin line."""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return [_Origin(line, node.value)]
        if isinstance(node, ast.Name) and node.id in self.constants:
            return [_Origin(line, self.constants[node.id])]
        starred = isinstance(node, ast.Starred)
        target = node.value if isinstance(node, ast.Starred) else node
        func = self.enclosing.get(id(node))
        if isinstance(target, ast.Name) and func is not None and depth < 8:
            return self._parameter(func, target.id, starred=starred, depth=depth)
        return [_Origin(line, _UNRESOLVED)]

    def _parameter(
        self, func: ast.FunctionDef, name: str, *, starred: bool, depth: int
    ) -> list[_Origin]:
        args = func.args
        positional = [a.arg for a in args.posonlyargs + args.args]
        callers = self.calls.get(func.name, [])
        found: list[_Origin] = []
        if starred and args.vararg is not None and args.vararg.arg == name:
            for call in callers:
                for arg in call.args[len(positional) :]:
                    found += self.expr(arg, call.lineno, depth + 1)
            return found or [_Origin(func.lineno, _UNRESOLVED)]
        if starred:
            return [_Origin(func.lineno, _UNRESOLVED)]
        default = self._default(func, name)
        index = positional.index(name) if name in positional else None
        is_param = index is not None or any(a.arg == name for a in args.kwonlyargs)
        if not is_param:
            return [_Origin(func.lineno, _UNRESOLVED)]
        for call in callers:
            passed = next((k.value for k in call.keywords if k.arg == name), None)
            if passed is None and index is not None and index < len(call.args):
                passed = call.args[index]
            if passed is None:
                passed = default
            if passed is None:
                found.append(_Origin(call.lineno, _UNRESOLVED))
            else:
                found += self.expr(passed, call.lineno, depth + 1)
        return found or [_Origin(func.lineno, _UNRESOLVED)]

    @staticmethod
    def _default(func: ast.FunctionDef, name: str) -> ast.expr | None:
        args = func.args
        positional = args.posonlyargs + args.args
        offset = len(positional) - len(args.defaults)
        for i, arg in enumerate(positional):
            if arg.arg == name and i >= offset:
                return args.defaults[i - offset]
        for arg, kw_default in zip(args.kwonlyargs, args.kw_defaults):
            if arg.arg == name:
                return kw_default
        return None


def _compose_up_lists(tree: ast.Module) -> list[ast.List | ast.Tuple]:
    """Every `[*COMPOSE, "up", ...]` literal in the file."""
    found: list[ast.List | ast.Tuple] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.List, ast.Tuple)) or len(node.elts) < 2:
            continue
        head, sub = node.elts[0], node.elts[1]
        if (
            isinstance(head, ast.Starred)
            and isinstance(head.value, ast.Name)
            and head.value.id == "COMPOSE"
            and isinstance(sub, ast.Constant)
            and sub.value == "up"
        ):
            found.append(node)
    return found


def _survey() -> tuple[list[str], set[int], int]:
    """(offending sites, agent origin lines, number of `compose up` lists)."""
    tree = ast.parse(TEST_FILE.read_text(encoding="utf-8"), filename=str(TEST_FILE))
    resolver = _Resolver(tree)
    agents = _agent_services()
    offenders: list[str] = []
    agent_origins: set[int] = set()
    lists = _compose_up_lists(tree)
    for node in lists:
        flags = {
            e.value
            for e in node.elts[2:]
            if isinstance(e, ast.Constant) and isinstance(e.value, str)
        }
        origins: list[_Origin] = []
        for element in node.elts[2:]:
            if isinstance(element, ast.Constant) and str(element.value).startswith("-"):
                continue
            origins += resolver.expr(element, node.lineno)
        hits = [o for o in origins if o.service in agents or o.service == _UNRESOLVED]
        agent_origins.update(o.line for o in hits if o.service in agents)
        if hits and "--no-deps" not in flags:
            named = ", ".join(
                sorted({f"{o.service} (from line {o.line})" for o in hits})
            )
            offenders.append(
                f"test_agent_e2e.py:{node.lineno}: `compose up` of {named}"
            )
    offenders.sort(key=lambda o: int(o.split(":")[1]))
    return offenders, agent_origins, len(lists)


def test_agent_services_are_the_ones_that_depend_on_the_server() -> None:
    """The guard's notion of 'agent service' comes from compose, not a list here."""
    assert {"cb-agent", "cb-agent-2"} <= _agent_services()
    assert SERVER_SERVICE not in _agent_services()


def test_every_agent_compose_up_passes_no_deps() -> None:
    offenders, _, _ = _survey()
    assert not offenders, (
        "These `docker compose up` calls start an agent service without --no-deps. "
        "The agent depends_on circuitbreaker, so compose may recreate the running "
        "server and kill every connection the test holds (see _enroll_agent):\n  "
        + "\n  ".join(offenders)
    )


def test_guard_sees_every_agent_up_site() -> None:
    """Positive control: the survey must find the agent starts, or it proves nothing."""
    _, origins, list_count = _survey()
    assert list_count >= 2, (
        f"found only {list_count} `compose up` lists; the parser is blind"
    )
    assert len(origins) >= MIN_AGENT_UP_SITES, (
        f"found {len(origins)} agent `compose up` sites, expected at least "
        f"{MIN_AGENT_UP_SITES}: lines {sorted(origins)}"
    )


def test_server_start_keeps_its_normal_semantics() -> None:
    """`_up_server` brings up the server itself and must not skip its deps."""
    tree = ast.parse(TEST_FILE.read_text(encoding="utf-8"), filename=str(TEST_FILE))
    resolver = _Resolver(tree)
    server_lists = [
        node
        for node in _compose_up_lists(tree)
        if any(
            o.service == SERVER_SERVICE
            for e in node.elts[2:]
            if not (isinstance(e, ast.Constant) and str(e.value).startswith("-"))
            for o in resolver.expr(e, node.lineno)
        )
    ]
    assert server_lists, "no `compose up circuitbreaker` found; _up_server moved?"
    for node in server_lists:
        flags = {e.value for e in node.elts if isinstance(e, ast.Constant)}
        assert "--no-deps" not in flags, (
            f"line {node.lineno}: the server start gained --no-deps"
        )
