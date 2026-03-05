"""Compatibility shim for third-party libraries that use deprecated APIs.

This module patches deprecated stdlib entry-points with their official
replacements before any library code runs.  Import it as the very first
application import in ``app/main.py`` and ``tests/conftest.py``.

Patches applied
---------------
asyncio.iscoroutinefunction → inspect.iscoroutinefunction
    Deprecated in Python 3.12, actively warns in Python 3.14+, and scheduled
    ``slowapi`` (≤ 0.1.9) performs the call via dynamic attribute lookup on the
    ``asyncio`` module object at call-time, so replacing the attribute on the module
    causes it to transparently use the correct implementation without any
    monkey-patching of the third-party package itself.

Remove this file when ``slowapi`` ships a release that uses
``inspect.iscoroutinefunction``.
"""

import asyncio
import inspect

# asyncio.iscoroutinefunction was soft-deprecated in Python 3.12 and emits
# DeprecationWarning in Python 3.14+.  The official replacement is
# inspect.iscoroutinefunction, which is behaviourally identical for all
# standard coroutine patterns used by the affected libraries.
if asyncio.iscoroutinefunction is not inspect.iscoroutinefunction:
    asyncio.iscoroutinefunction = inspect.iscoroutinefunction  # type: ignore[attr-defined]
