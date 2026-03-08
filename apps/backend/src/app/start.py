"""
Startup wrapper that patches socket.socketpair for restricted container
environments (e.g. Proxmox LXC) where AF_UNIX socketpair is blocked by seccomp.

Python's asyncio always calls socket.socketpair() when initializing any event
loop on Unix. When that syscall is blocked, we substitute an equivalent pair of
connected TCP loopback sockets, which asyncio's _make_self_pipe uses identically.
"""

import os
import sys
from pathlib import Path

# Ensure backend/src is on sys.path so 'import app' resolves correctly
# regardless of WORKDIR or whether the package is installed in site-packages.
# __file__ is backend/src/app/start.py → backend/src is 2 levels up.
_src_root = str(Path(__file__).resolve().parent.parent)
if _src_root not in sys.path:
    sys.path.insert(0, _src_root)

import socket  # noqa: E402

_orig_socketpair = socket.socketpair


def _tcp_socketpair():
    """Return a connected TCP socket pair as a drop-in replacement for socketpair."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.connect(("127.0.0.1", port))
    conn, _ = server.accept()
    server.close()
    return conn, client


def _safe_socketpair(family=socket.AF_UNIX, type=socket.SOCK_STREAM, proto=0):
    try:
        return _orig_socketpair(family, type, proto)
    except PermissionError:
        return _tcp_socketpair()


socket.socketpair = _safe_socketpair

import uvicorn  # noqa: E402

# Production default: 1 worker to minimise memory footprint on low-RAM devices
# (e.g. Raspberry Pi 4 with 1 GB). Scale up with UVICORN_WORKERS=2+ on
# higher-spec machines.  Dev mode (--reload) requires exactly 1 worker anyway.
_workers = int(os.environ.get("UVICORN_WORKERS", "1"))

if __name__ == "__main__":
    from app.main import run_alembic_upgrade

    run_alembic_upgrade()

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        loop="asyncio",
        workers=_workers,
    )
