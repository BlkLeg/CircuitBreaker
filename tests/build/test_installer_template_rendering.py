"""Rendered templates are data, and the renderer must treat them that way.

install.sh used to render every config and unit file through an unquoted
heredoc inside an `eval`:

    eval "cat <<__CB_TEMPLATE_EOF__
    $(cat "$src")
    __CB_TEMPLATE_EOF__" > "$dest"

which expanded the *entire file* as shell. Two consequences, both shipped in
v0.4.0:

* **Backticks in prose executed as root.** The nginx configs documented their
  routing with `` `curl https://cb.example.com/install-agent.sh` `` and
  `` `sha256sum -c` ``, so every install ran both — an outbound request on a
  platform whose air-gap contract forbids one, and a `sha256sum -c` with no
  argument, which reads stdin and blocks.
* **An unset variable killed the installer.** Under `set -u`, AGT-11's comment
  "$TMPDIR/_MEI<random>" aborted every install on a host where TMPDIR was unset.

The renderer now substitutes `${NAME}` and copies every other byte through. The
tests below pin that behaviour by *running it*, because the property that
matters — "this input produces exactly this output, and executes nothing" — is
not something grepping the source can establish.
"""

from __future__ import annotations

import re
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SETUP = REPO_ROOT / "deploy" / "setup.sh"
INSTALLER = REPO_ROOT / "install.sh"

# Shell-expansion forms the substituting renderer does NOT implement. They are
# not dangerous any more, which is the problem: they would be copied through
# literally and land in a live config as the text "${FOO:-bar}". Anything that
# needs shell is computed in setup.sh and passed as a plain ${NAME}.
UNSUPPORTED_FORMS = (
    (r"\$\(", "$( ) command substitution"),
    (r"\$\{[A-Za-z_][A-Za-z0-9_]*[:+#%/^,-]", "${NAME:-default} style expansion"),
)


def _rendered_templates() -> list[Path]:
    text = SETUP.read_text(encoding="utf-8")
    installed = re.findall(r'cb_render_template "(/opt/circuitbreaker/deploy/[^"]+)"', text)
    paths = [REPO_ROOT / "deploy" / p.split("/opt/circuitbreaker/deploy/", 1)[1] for p in installed]
    paths.append(REPO_ROOT / "deploy" / "misc" / ".env.template")
    assert len(paths) > 10, f"only found {len(paths)} rendered templates; did the call shape change?"
    return sorted(set(paths))


def _renderer_source() -> str:
    """The three renderer functions, lifted from install.sh so the test exercises
    the shipped implementation rather than a copy of it."""
    text = INSTALLER.read_text(encoding="utf-8")
    out = []
    for name in ("cb_template_vars", "cb_replace_all", "cb_render_template"):
        body = re.search(rf"^{name}\(\)\s*\{{.*?^\}}", text, re.DOTALL | re.MULTILINE)
        assert body, f"install.sh no longer defines {name}"
        out.append(body.group(0))
    return "\n".join(out)


def _render(tmp_path: Path, template: str, env_assignments: str) -> subprocess.CompletedProcess[str]:
    src = tmp_path / "in.tmpl"
    src.write_text(template, encoding="utf-8")
    script = textwrap.dedent(f"""
        set -euo pipefail
        cb_fail() {{ echo "CB_FAIL: $1" >&2; exit 9; }}
        {_renderer_source()}
        {env_assignments}
        cb_render_template "{src}" "{tmp_path / 'out.conf'}"
    """)
    return subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},  # deliberately no TMPDIR
    )


def test_the_renderer_executes_nothing_in_a_template(tmp_path):
    """Backticks and $( ) in a config comment used to run as root."""
    canary = tmp_path / "canary"
    hostile = (
        f"# prose with `touch {canary}` and $(touch {canary})\n"
        "# and a mention of $TMPDIR/_MEI<random>\n"
        "proxy_set_header X-Real-IP $remote_addr;\n"
        "ExecReload=/bin/kill -HUP $MAINPID\n"
        "dir ${CB_DATA_DIR};\n"
    )
    result = _render(tmp_path, hostile, "CB_DATA_DIR=/var/lib/circuitbreaker")

    assert result.returncode == 0, f"render failed: {result.stderr}"
    assert not canary.exists(), (
        "the renderer executed a command found in the template. Rendering runs as "
        "root during install; a backtick in a prose comment must be text."
    )
    rendered = (tmp_path / "out.conf").read_text(encoding="utf-8")
    assert f"`touch {canary}`" in rendered and f"$(touch {canary})" in rendered
    assert "$TMPDIR/_MEI<random>" in rendered, "unset $TMPDIR must pass through, not abort"
    assert "$remote_addr" in rendered and "$MAINPID" in rendered, (
        "unbraced variables belong to nginx and systemd, not to the shell — they "
        "must reach the rendered file untouched and without backslash-escaping"
    )
    assert "dir /var/lib/circuitbreaker;" in rendered


def test_values_containing_shell_metacharacters_render_verbatim(tmp_path):
    """Bash's ${v//pat/rep} treats `&` in the replacement as the matched text from
    5.2 on, so a proxy URL would render differently on Ubuntu 22.04 and 24.04."""
    result = _render(
        tmp_path,
        "CB_EGRESS_PROXY_URL=${CB_EGRESS_PROXY_URL}\n",
        r"""CB_EGRESS_PROXY_URL='http://p.example:8080/?a=1&b=2&c=\x'""",
    )
    assert result.returncode == 0, f"render failed: {result.stderr}"
    assert (
        (tmp_path / "out.conf").read_text(encoding="utf-8").strip()
        == r"CB_EGRESS_PROXY_URL=http://p.example:8080/?a=1&b=2&c=\x"
    ), "a value containing & or a backslash must survive substitution byte for byte"


def test_a_template_asking_for_an_unset_variable_fails_loudly(tmp_path):
    """Better a named refusal than a config written with a blank password."""
    result = _render(tmp_path, "password ${CB_NEVER_SET_ANYWHERE};\n", "true")
    assert result.returncode == 9, (
        "a ${NAME} the installer never sets must stop the install. Rendering it as "
        "an empty string writes a config with a blank secret, which fails later and "
        "somewhere else."
    )
    assert "CB_NEVER_SET_ANYWHERE" in result.stderr, "the error must name the variable"


def test_every_template_variable_is_one_the_installer_sets():
    """The static half of the check above, across the real templates."""
    setup_text = SETUP.read_text(encoding="utf-8")
    assigned = set(
        re.findall(r"(?:^|\s)(?:export |local |declare )?([A-Za-z_][A-Za-z0-9_]*)=", setup_text)
    )
    offenders: list[str] = []
    for template in _rendered_templates():
        assert template.is_file(), f"{template} is rendered but does not exist"
        rel = template.relative_to(REPO_ROOT).as_posix()
        for name in sorted(
            set(re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", template.read_text(encoding="utf-8")))
        ):
            if name not in assigned:
                offenders.append(f"{rel}: ${{{name}}}")
    assert not offenders, (
        "these templates ask for variables deploy/setup.sh never assigns, so the "
        "render aborts the install:\n  " + "\n  ".join(offenders)
    )


def test_no_template_uses_an_expansion_the_renderer_does_not_implement():
    """These used to work by accident under `eval`, and would now be emitted as
    literal text into a live config."""
    offenders: list[str] = []
    for template in _rendered_templates():
        rel = template.relative_to(REPO_ROOT).as_posix()
        text = template.read_text(encoding="utf-8")
        for pattern, label in UNSUPPORTED_FORMS:
            for match in re.finditer(pattern, text):
                line = text[: match.start()].count("\n") + 1
                offenders.append(f"{rel}:{line}: {label}")
    assert not offenders, (
        "the renderer substitutes plain ${NAME} only. These forms would be copied "
        "into the rendered file as literal text — compute them in deploy/setup.sh "
        "and pass the result as a plain ${NAME}, the way CB_APP_HOST and "
        "CB_INSTALL_DATE replaced ${CB_FQDN:-$CB_DETECTED_IP} and $(date):\n  "
        + "\n  ".join(offenders)
    )


def test_templates_carry_no_leftover_eval_escaping():
    r"""\$host and \$MAINPID existed only to survive the eval. Left in place they
    would now render as a literal backslash into nginx and systemd configs."""
    offenders: list[str] = []
    for template in _rendered_templates():
        rel = template.relative_to(REPO_ROOT).as_posix()
        text = template.read_text(encoding="utf-8")
        for match in re.finditer(r"\\[$`]", text):
            line = text[: match.start()].count("\n") + 1
            offenders.append(f"{rel}:{line}: {match.group(0)}")
    assert not offenders, (
        r"backslash-escaped $ or ` left over from the eval renderer. The renderer "
        r"no longer evaluates templates, so \$host now renders as the literal "
        r"text \$host and breaks the config:" + "\n  " + "\n  ".join(offenders)
    )
