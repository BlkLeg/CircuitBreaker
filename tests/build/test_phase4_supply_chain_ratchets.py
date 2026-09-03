"""Phase 4 repo-policy ratchets (route findings F4, F3).

These are Tier 0 gates: they read source text, never run the app, and they
exist because each finding they cover is a *class* of defect that came back
after being fixed once.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_SRC = REPO_ROOT / "apps" / "agent"

# The only files allowed to name cfg.TLSPin: the config struct that declares
# it, and the one resolver that turns it into a trust policy. Every dial site
# must go through link.ResolveTrust instead.
_TLS_PIN_ALLOWLIST = {
    Path("internal/config/config.go"),
    Path("internal/link/trust.go"),
}


def _go_sources() -> list[Path]:
    return [
        p
        for p in AGENT_SRC.rglob("*.go")
        if not p.name.endswith("_test.go") and "/vendor/" not in p.as_posix()
    ]


def test_no_go_source_reads_tls_pin_directly() -> None:
    """F4: cfg.TLSPin fed four dial sites — enrollment, the /link socket, its
    re-dial, and the update binary download — and nothing ever rewrote it, so
    a certificate change stranded the agent on every path at once, including
    the one that would have delivered a fix.

    One resolver (link.ResolveTrust) now owns that translation. A new
    reference to cfg.TLSPin outside the allowlist means a fifth dial site
    that will not see an advertised successor.
    """
    offenders: list[str] = []
    pattern = re.compile(r"\bTLSPin\b")
    for path in _go_sources():
        rel = path.relative_to(AGENT_SRC)
        if rel in _TLS_PIN_ALLOWLIST:
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("//"):
                continue
            if pattern.search(line):
                offenders.append(f"{rel}:{lineno}: {stripped}")
    assert not offenders, (
        "TLSPin must only be read by internal/config (which declares it) and "
        "internal/link/trust.go (which resolves it into a tlsdial.Trust). "
        "Every dial site goes through link.ResolveTrust so an advertised "
        "successor policy reaches all of them:\n  " + "\n  ".join(offenders)
    )


def test_every_dialer_and_transport_call_takes_a_resolved_trust() -> None:
    """The companion to the check above: a call site could construct a
    tlsdial.Trust literal inline and bypass the resolver without ever naming
    TLSPin. Every NewDialer/NewTransport call must be handed either
    ResolveTrust(...) or a variable, never a Trust literal."""
    offenders: list[str] = []
    call = re.compile(r"tlsdial\.New(?:Dialer|Transport)\(\s*tlsdial\.Trust\{")
    for path in _go_sources():
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if call.search(line):
                offenders.append(f"{path.relative_to(AGENT_SRC)}:{lineno}: {line.strip()}")
    assert not offenders, (
        "Build the trust policy with link.ResolveTrust rather than an inline "
        "tlsdial.Trust literal — a literal cannot pick up an advertised "
        "successor:\n  " + "\n  ".join(offenders)
    )


# The exact set of agent events that carry a hash-chained audit entry.
# Changing this requires changing the test, which is the point: adding an
# authorization event without chaining it is the F17 defect returning, and
# adding a high-volume one puts it behind the global audit advisory lock.
_EXPECTED_CHAINED_EVENTS = {
    "enrolled",
    "approved",
    "rejected",
    "revoked",
    "capability_changed",
    "key_rotation_started",
    "key_rotated",
    "key_rotation_rejected",
    "key_rotation_expired",
    "update_queued",
}


def _chained_event_types() -> set[str]:
    """Read `CHAINED_EVENT_TYPES` out of the source with AST rather than by
    importing it.

    This is a Tier 0 gate: importing `app.services.agent_registry` pulls in
    `app.db.session`, which refuses to load without a `CB_DB_URL`. A static
    gate that needs a database is not a static gate — and the rest of this
    tier reads source for the same reason (see tests/build/_ast_helpers.py).
    """
    source = (
        REPO_ROOT / "apps" / "backend" / "src" / "app" / "services" / "agent_registry.py"
    ).read_text()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "CHAINED_EVENT_TYPES" not in targets:
            continue
        # frozenset({...}) — the literal set is the single call argument.
        assert isinstance(node.value, ast.Call), "CHAINED_EVENT_TYPES must stay a literal"
        return {ast.literal_eval(elt) for elt in node.value.args[0].elts}
    raise AssertionError("CHAINED_EVENT_TYPES not found in agent_registry.py")


def test_chained_agent_event_set_is_pinned() -> None:
    """F17: agent authorization decisions must be tamper-evident, and only
    those — the audit chain serializes on a global advisory lock, so a
    high-volume event type added here becomes an instance-wide contention
    point."""
    assert _chained_event_types() == _EXPECTED_CHAINED_EVENTS


def test_high_volume_events_are_never_chained() -> None:
    """Named individually rather than left to the set comparison above, so
    the reason each one is excluded survives a future edit to that set."""
    chained = _chained_event_types()

    for event in (
        "connected",
        "disconnected",
        "version_changed",
        "capability_violation",
        "protocol_violation",
        "host_link_changed",
    ):
        assert event not in chained, (
            f"{event!r} is high-volume or not an authorization decision; "
            "chaining it serializes it behind the global audit lock"
        )


RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"
BUILD_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "build.yml"


def test_release_workflow_supplies_the_agent_signing_key() -> None:
    """F3: a signer that is defined but never invoked ships a feature that has
    never run — the exact defect test_encrypted_backup_contract.py was written
    after. Both halves must reach the build: the private key the manifest
    generator signs with, and the public key the agent build embeds.

    Checked across *both* workflows on purpose. release.yml only calls the
    reusable build workflow, so asserting on it alone would pass while
    build.yml quietly ignored what it was handed — which is this test's own
    failure mode, one indirection further out.
    """
    release = RELEASE_WORKFLOW.read_text()
    build = BUILD_WORKFLOW.read_text()

    assert "secrets.AGENT_SIGNING_PRIVATE_KEY" in release, (
        "release.yml must pass AGENT_SIGNING_PRIVATE_KEY down to the build "
        "workflow from the secret store, or every released binary ships "
        "unsigned. Secrets do not cross into a reusable workflow on their own"
    )
    assert "signing_pubkey" in release, (
        "release.yml must pass the public key down to the build workflow, or "
        "released agents have no embedded key and can never enforce"
    )

    assert "AGENT_SIGNING_PRIVATE_KEY: ${{ secrets.AGENT_SIGNING_PRIVATE_KEY }}" in build, (
        "build.yml must put the private key in the build step's env, where "
        "apps/agent/scripts/gen_manifest.py reads it"
    )
    assert "SIGNING_PUBKEY: ${{ inputs.signing_pubkey }}" in build, (
        "build.yml must put the public key in the build step's env, where "
        "apps/agent/Makefile turns it into the -X ldflag"
    )


# A PEM header alone is not key material — the repo legitimately carries
# placeholder certificate fixtures whose bodies are a few characters
# (apps/backend/tests/services/test_agent_install.py). Real key material has a
# substantial base64 body, so that is what this looks for.
_PEM_KEY_BODY = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"
    r"(?P<body>[A-Za-z0-9+/=\s]{200,}?)"
    r"-----END (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"
)


def _tracked_files() -> list[Path]:
    """Every file git tracks, which is the set this gate is actually about.

    Deliberately `git ls-files` and not a filesystem walk. The constraint is
    that no key material is *committed*; a working-tree scan instead reports
    whatever a developer happens to have lying around — this checkout's
    gitignored `e2e-data/tls/privkey.pem`, generated by an E2E run, and the
    `moto` test keys inside `.venv-release/`. Neither is in the repository,
    and a gate that is red on arrival for things nobody committed gets muted
    rather than obeyed, which is how the constraint would quietly stop being
    enforced. It is also immune to a skip-list going stale as new build and
    virtualenv directories appear.
    """
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
        text=True,
    ).stdout
    return [REPO_ROOT / name for name in out.split("\0") if name]


def test_no_private_key_material_is_committed() -> None:
    """Global constraint: no signing material in the repo, including tests,
    examples and fixtures. Every test generates its keypair at runtime.

    Matches on a substantial base64 body rather than a bare PEM header: the
    header alone flags the repository's legitimate placeholder certificate
    fixtures, and a gate that is red on arrival gets muted rather than obeyed.
    """
    offenders: list[str] = []
    for path in _tracked_files():
        # This file names the markers it searches for, so it always matches
        # itself.
        if not path.is_file() or path.resolve() == Path(__file__).resolve():
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        if _PEM_KEY_BODY.search(text):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, f"private key material committed: {offenders}"


def test_the_mono_image_signs_its_agent_binaries_too() -> None:
    """H2. The ratchet above proved the *native* build reaches the signer and
    stopped there, so the mono image — the primary shipping artifact, and the
    one most installs actually run — built every agent binary with no embedded
    key and no `.sig` beside it. Slice 4.2 had no effect there at all.

    That is this suite's own recorded failure mode: it was written to catch "a
    signer that is defined but never invoked", and it missed a whole build path
    because it only ever looked at one.

    The private key must arrive as a BuildKit secret rather than a build arg.
    Build args are recorded in image metadata and readable with `docker
    history`; leaking the agent signing key that way would be worse than
    shipping unsigned.
    """
    raw = (REPO_ROOT / "Dockerfile.mono").read_text()
    # Directives only. A plain substring search over the whole file passes on a
    # commented-out `# ARG SIGNING_PUBKEY=`, which is the exact way the gates
    # this suite replaced failed to notice anything: they asserted that a string
    # appeared, not that the build does the thing.
    dockerfile = "\n".join(
        line for line in raw.splitlines() if not line.lstrip().startswith("#")
    )
    release = RELEASE_WORKFLOW.read_text()

    assert "ARG SIGNING_PUBKEY" in dockerfile, (
        "Dockerfile.mono's agent-builder stage must accept SIGNING_PUBKEY, or "
        "mono-image agents carry no embedded key and can never enforce"
    )
    assert 'make manifest SIGNING_PUBKEY="${SIGNING_PUBKEY}"' in dockerfile, (
        "the public key must reach `make manifest`; accepting the ARG and not "
        "passing it on is the same defect one step later"
    )
    assert "--mount=type=secret,id=agent_signing_key" in dockerfile, (
        "the private key must be mounted as a BuildKit secret in the stage that "
        "runs gen_manifest.py"
    )
    assert "python3-cryptography" in dockerfile, (
        "gen_manifest.py's signing branch imports cryptography; without it a "
        "build handed a key fails instead of signing"
    )

    assert "--secret id=agent_signing_key" in release, (
        "release.yml's image build must pass the signing key as a BuildKit "
        "secret, or the mono image ships unsigned binaries"
    )
    assert "--build-arg SIGNING_PUBKEY=" in release, (
        "release.yml's image build must pass the public key through"
    )
    assert "--build-arg AGENT_SIGNING_PRIVATE_KEY" not in release, (
        "the private key must never be a build arg — build args are recorded in "
        "image metadata and readable with `docker history`"
    )


def test_no_agent_dial_bypasses_tlsdial_entirely() -> None:
    """G4. The two checks above both assume the dial goes through `tlsdial`.

    Neither can see a fifth dial site that does not. A bare `http.Get`, an
    `&http.Client{}` with its own transport, or a `&websocket.Dialer{}` literal
    names no `TLSPin` and matches no `tlsdial.New...(tlsdial.Trust{` literal, so
    both stay green while the agent talks to the server under a trust policy no
    rotation can reach — F4 returning by the one route that pair was written to
    close.

    Client and dialer literals are judged by what they are *given*: legitimate
    ones take `tlsdial.NewTransport(...)` (see `internal/update/update.go`,
    which is exactly this shape and is correct). `http.Get` and
    `websocket.DefaultDialer` can carry no transport at all, so they are always
    a bypass.

    Two packages are exempt because they do not talk to Circuit Breaker: the
    monitoring probe dials whatever target an operator configured, and the
    Docker collector dials a local unix socket. Neither has a pin to honour.
    """
    exempt = {
        "internal/tlsdial/tlsdial.go",  # the wrapper itself
        "internal/collect/probe/http.go",  # user-configured probe targets
        "internal/collect/host/docker.go",  # local unix socket
    }
    # `\b` cannot precede `&` — both are non-word characters, so an earlier
    # version of this pattern silently matched nothing that mattered.
    needs_transport = re.compile(r"&(?:http\.Client|websocket\.Dialer)\{")
    always_bypass = re.compile(
        r"\bhttp\.(?:Get|Post|Head|PostForm)\(|\bwebsocket\.DefaultDialer\b"
    )
    offenders: list[str] = []

    for path in _go_sources():
        relative = str(path.relative_to(AGENT_SRC))
        if relative in exempt:
            continue
        lines = path.read_text().splitlines()
        for lineno, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("//"):
                continue
            if always_bypass.search(line):
                offenders.append(f"{relative}:{lineno}: {stripped}")
            elif needs_transport.search(line):
                # The literal's own block: a pinned client hands its transport
                # in right here.
                block = "\n".join(lines[lineno - 1 : lineno + 5])
                if "tlsdial." not in block:
                    offenders.append(f"{relative}:{lineno}: {stripped}")

    assert not offenders, (
        "an outbound dial bypasses internal/tlsdial, so an advertised successor "
        "TLS policy cannot reach it. A stranded agent cannot be repaired "
        "remotely, because the update download is stranded with everything "
        "else:\n  " + "\n  ".join(offenders)
    )


def test_the_chained_event_set_is_actually_consulted() -> None:
    """G5. The check above pins the constant's *contents*. It says nothing
    about whether anything reads it.

    Delete the `if event_type in CHAINED_EVENT_TYPES:` branch in `record_event`
    and every assertion above still passes: the set is intact, correct, and
    inert. That is the same shape as the four defects slice 4.1 recorded — a
    mechanism that looks right at every layer and does nothing — and it is what
    a gate written for exactly that failure mode should be least willing to
    miss.
    """
    source = (
        REPO_ROOT / "apps" / "backend" / "src" / "app" / "services" / "agent_registry.py"
    ).read_text()
    tree = ast.parse(source)

    record_event = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "record_event"
        ),
        None,
    )
    assert record_event is not None, "record_event has moved; this gate needs updating with it"

    reads_the_set = any(
        isinstance(node, ast.Name) and node.id == "CHAINED_EVENT_TYPES"
        for node in ast.walk(record_event)
    )
    assert reads_the_set, (
        "record_event no longer consults CHAINED_EVENT_TYPES, so agent "
        "authorization events are not reaching the hash-chained audit log — F17, "
        "with the constant left behind to make it look handled"
    )

    # Name *and* Attribute: the call is `write_log(...)` from a function-local
    # import today, and an attribute-only check would have read as satisfied by
    # nothing at all — the exact narrowness this suite keeps finding elsewhere.
    writes_the_chain = any(
        (isinstance(node, ast.Name) and node.id == "write_log")
        or (isinstance(node, ast.Attribute) and node.attr == "write_log")
        for node in ast.walk(record_event)
    )
    assert writes_the_chain, (
        "record_event reads the set but never calls log_service.write_log; the "
        "chained write is what makes the decision tamper-evident"
    )


def test_no_authorization_event_is_recorded_without_a_decision() -> None:
    """The set is one-directional: nothing stops a *new* authorization event
    type being passed to `record_event` and quietly never chained.

    So every event-type literal handed to `record_event` anywhere in the app is
    collected here, and any name that reads like an authorization decision has
    to be either chained or listed as a deliberate exclusion. The point is that
    adding one forces a choice, which the constant alone could not do.
    """
    chained = _chained_event_types()
    app_root = REPO_ROOT / "apps" / "backend" / "src" / "app"

    #: Authorization-shaped names that are deliberately not chained, with the
    #: reason they are safe to leave out.
    deliberate_exclusions = {
        # High-volume, agent-driven, and already throttled — chaining them
        # would trade a write-amplification problem for instance-wide lock
        # contention. See test_high_volume_events_are_never_chained.
        "capability_violation",
        "protocol_violation",
    }
    authorization_markers = (
        "approv",
        "reject",
        "revok",
        "enroll",
        "authoriz",
        "key_rotation",
        "permission",
        "grant",
        "deny",
    )

    unchained: list[str] = []
    for path in sorted(app_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr
                if isinstance(node.func, ast.Attribute)
                else None
            )
            if name != "record_event":
                continue
            for arg in list(node.args) + [kw.value for kw in node.keywords]:
                if not isinstance(arg, ast.Constant) or not isinstance(arg.value, str):
                    continue
                event = arg.value
                if event in chained or event in deliberate_exclusions:
                    continue
                if any(marker in event for marker in authorization_markers):
                    unchained.append(f"{path.relative_to(app_root)}:{node.lineno}: {event!r}")

    assert not unchained, (
        "an authorization-shaped agent event is recorded without a hash-chained "
        "entry:\n  "
        + "\n  ".join(unchained)
        + "\n\nAdd it to CHAINED_EVENT_TYPES, or to this test's "
        "deliberate_exclusions with the reason it is safe to leave out."
    )


#: Environment variables whose value is signing or encryption material. A
#: literal assigned to any of these is a committed secret whatever file it is
#: in — CLAUDE.md's rule names tests, fixtures, examples and CI explicitly.
_SECRET_ENV_NAMES = (
    "CB_JWT_SECRET",
    "CB_VAULT_KEY",
    "NATS_AUTH_TOKEN",
    "AGENT_SIGNING_PRIVATE_KEY",
    "CB_API_TOKEN",
)


def test_no_secret_env_var_is_assigned_a_literal() -> None:
    """The PEM check above sees only PEM bodies.

    It could not see the three literals that were actually committed: a JWT
    signing secret, a working base64 Fernet vault key, and a bus token, all in
    `apps/backend/tests/conftest.py`, all readable by anyone with the
    repository. A base64 Ed25519 seed — the shape the agent signing key takes —
    is equally invisible to it.

    So this matches on the *name* being assigned rather than on the value's
    shape. A secret's value can look like anything; the variable it lands in
    cannot.

    Matched only on real assignment syntax. A first version matched any
    `NAME` followed by `=` or `:` and a quoted string, which flagged
    `assert "CB_VAULT_KEY=" in content` and `{"CB_JWT_SECRET": "change_me"}` —
    a test asserting the placeholder is *rejected*. A gate red on arrival gets
    muted, so it has to be right about what an assignment is.
    """
    names = "|".join(_SECRET_ENV_NAMES)
    forms = (
        # os.environ["NAME"] = "literal"  /  os.environ.setdefault("NAME", "literal")
        re.compile(rf"os\.environ(?:\[|\.setdefault\()\s*[\"\']({names})[\"\']\s*[\],]\s*=?\s*[\"\']([^\"\'\n]+)"),
        # export NAME="literal" at the start of a shell line
        re.compile(rf"^\s*(?:export\s+)?({names})=[\"\']([^\"\'\n]+)[\"\']"),
        # export NAME=literal, unquoted — stops at whitespace, or the value
        # swallows the rest of the command line after it.
        re.compile(rf"^\s*(?:export\s+)?({names})=([^\s\"\'\n\\]+)"),
        # NAME: literal in YAML
        re.compile(rf"^\s*-?\s*({names}):\s+[\"\']?([^\"\'\n]+)"),
    )
    #: Values that are read from somewhere rather than written down.
    generated_markers = (
        "${",
        "$(",
        "$",
        "os.environ",
        "getenv",
        "secrets.token",
        "Fernet.generate",
        "openssl",
        "rand",
        "generate_key",
        "uuid",
    )
    #: `make dev` starts a local broker and a local backend that must agree on a
    #: token. This is a pairing between two processes on one developer's laptop,
    #: not secret material — and randomising it would break `make dev` unless
    #: both sides read the same generated value, which is a change to the dev
    #: workflow rather than a security fix. Named here so the exemption is a
    #: decision rather than a gap.
    exempt_files = {"Makefile"}

    offenders: list[str] = []
    for path in _tracked_files():
        if not path.is_file() or path.resolve() == Path(__file__).resolve():
            continue
        relative = str(path.relative_to(REPO_ROOT))
        if relative in exempt_files:
            continue
        if path.suffix not in {".py", ".sh", ".yml", ".yaml", ".toml", ".env", ".conf", ""}:
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith("//") or "assert" in stripped:
                continue
            for form in forms:
                match = form.search(line)
                if not match:
                    continue
                value = match.group(2).strip()
                if any(marker in value for marker in generated_markers):
                    continue
                # Documentation placeholders: `CB_VAULT_KEY="<key>"` in a usage
                # example, or `CB_API_TOKEN=MY_API_TOKEN_123` in a docstring
                # showing how to run a suite. Neither is a secret, and flagging
                # them teaches people to mute the gate.
                if "<" in value and ">" in value:
                    continue
                if re.fullmatch(r"[A-Z][A-Z0-9_]*", value):
                    continue
                offenders.append(f"{relative}:{lineno}: {match.group(1)} assigned a literal")
                break

    assert not offenders, (
        "signing or encryption material is committed:\n  "
        + "\n  ".join(offenders)
        + "\n\nGenerate it at runtime (secrets.token_urlsafe, Fernet.generate_key, "
        "openssl rand) or inject it from the secret store. CLAUDE.md's rule covers "
        "tests, fixtures, examples and CI workflows."
    )
