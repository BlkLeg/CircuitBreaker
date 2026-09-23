# Vendored pure-Python wheels

PyPI publishes some packages Circuit Breaker needs only as sdists
(`python-nmap`). `scripts/pbs_tree.py` installs with `--only-binary=:all:`,
so those packages would fail the build even though they need no compiler.

Rebuild a wheel (no compiler required for pure Python) and drop it here:

```bash
.venv/bin/python -m pip wheel --no-deps -w packaging/wheels python-nmap==<version>
```

Bump the pin in `apps/backend/pyproject.toml` / `poetry.lock` together with
the wheel filename.
