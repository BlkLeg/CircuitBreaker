# Vendored pure-Python wheels

PyPI publishes some packages Circuit Breaker needs only as sdists
(`python-nmap`). `scripts/pbs_tree.py` installs with `--only-binary=:all:`,
so those packages would fail the build even though they need no compiler.

Every `*.whl` here must have a sibling `*.whl.sha256` whose first token is the
**content SHA-256 of the committed wheel bytes** (not a PyPI sdist hash).
`scripts/pbs_tree.py` verifies each sidecar before `--find-links` install; a
missing or mismatched digest fails the build the same way a PBS pin mismatch
does.

Rebuild a wheel (no compiler required for pure Python) and pin it:

```bash
.venv/bin/python -m pip wheel --no-deps -w packaging/wheels python-nmap==<version>
sha256sum packaging/wheels/python_nmap-<version>-*.whl \
  | awk '{print $1}' > packaging/wheels/python_nmap-<version>-*.whl.sha256
```

(Write the hex digest alone, or `hex  filename` — only the first token is read.)

Bump the pin in `apps/backend/pyproject.toml` / `poetry.lock` together with
the wheel filename and its `.sha256` sidecar.
