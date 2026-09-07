"""Static asset mounts, the ACME webroot and the SPA fallback.

Registered last, deliberately: ``GET /{full_path:path}`` matches every GET path
no router claimed, so anything mounted after it is unreachable.  ``main`` calls
:func:`register` as its final act for that reason, and :func:`register` keeps
the mounts in the order the fallback depends on.

Kept out of ``main`` because resolving a frontend build across four packaging
layouts, three upload directories and a webroot that may not exist yet has
nothing to do with composing the API.
"""

import logging
import mimetypes
import os
from collections.abc import Awaitable, Callable
from pathlib import Path, PurePosixPath

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.services.acme_service import webroot as _acme_webroot
from app.startup.paths import APP_DIR

_logger = logging.getLogger(__name__)

_FAVICON_FILENAME = "favicon.ico"
_STATIC_DIR = APP_DIR.parent / "static"
_FRONTEND_DIST = APP_DIR.parent / "frontend" / "dist"


def _get_frontend_dir() -> Path | None:
    # Prefer settings.static_dir which maps to the STATIC_DIR env var.
    # The Dockerfile sets STATIC_DIR=/app/frontend/dist; the default "../frontend/dist"
    # is resolved relative to the backend working directory (/app/backend in Docker).
    sd = Path(settings.static_dir)
    if not sd.is_absolute():
        sd = Path.cwd() / sd
    if sd.exists():
        return sd
    # Legacy fallbacks for local dev layouts
    if _FRONTEND_DIST.exists():
        return _FRONTEND_DIST
    if _STATIC_DIR.exists():
        return _STATIC_DIR
    return None


_frontend_dir = _get_frontend_dir()
_frontend_root_files: dict[str, Path] = {}
if _frontend_dir:
    _frontend_dir_resolved = _frontend_dir.resolve()
    for _entry in _frontend_dir_resolved.iterdir():
        if _entry.is_file():
            _frontend_root_files[_entry.name] = _entry

_uploads_dir = Path(settings.uploads_dir)
_user_icons_dir = _uploads_dir / "icons"
_branding_dir_data = _uploads_dir / "branding"

# Ensure directories exist so mounting never fails
_uploads_dir.mkdir(parents=True, exist_ok=True)
_user_icons_dir.mkdir(parents=True, exist_ok=True)
_branding_dir_data.mkdir(parents=True, exist_ok=True)


class _AcmeChallengeFiles(StaticFiles):
    """StaticFiles pinned to `acme_service.webroot()` as it is at request time.

    The CA fetches this path with no credentials, before any certificate exists. nginx serves
    it directly in the mono image and on a native install; the plain image has no nginx, so the
    application serves the same webroot certbot writes into. One directory, two servers.

    The webroot is resolved per request rather than at import: CB_DATA_DIR is what names it,
    the directory does not exist until the first issuance, and a `/data` that this process
    cannot create must not be able to stop the application from importing.

    The assignment in `lookup_path` writes shared instance state from a request handler, which
    is safe here for one reason and only one: `webroot()` reads CB_DATA_DIR, which is fixed for
    the life of the process, so every request writes the identical value. Starlette's own
    traversal guard still runs in `super().lookup_path`, so a token containing `..` cannot
    escape the directory this names.
    """

    def __init__(self) -> None:
        super().__init__(directory=None, check_dir=False)

    def lookup_path(self, path: str) -> tuple[str, os.stat_result | None]:
        self.all_directories = [str(_acme_webroot() / ".well-known" / "acme-challenge")]
        return super().lookup_path(path)


async def _static_cache_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Add Cache-Control for static uploads so browsers cache icons and branding."""
    response = await call_next(request)
    path = request.scope.get("path", "")
    if path.startswith(("/uploads/", "/user-icons/", "/branding/")) and response.status_code == 200:
        response.headers.setdefault("Cache-Control", "public, max-age=86400")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers.setdefault("Content-Security-Policy", "default-src 'none'; img-src 'self'")
        if path.lower().endswith((".svg", ".svgz", ".html", ".htm", ".xhtml", ".xml")):
            response.headers["Content-Type"] = "application/octet-stream"
            response.headers["Content-Disposition"] = "attachment"
    return response


async def favicon_file() -> Response:
    favicon = _branding_dir_data / _FAVICON_FILENAME
    if favicon.exists():
        return FileResponse(str(favicon), media_type="image/x-icon")
    if _frontend_dir and (_frontend_dir / _FAVICON_FILENAME).exists():
        return FileResponse(str(_frontend_dir / _FAVICON_FILENAME), media_type="image/x-icon")
    return Response(status_code=404)


def get_install_agent_script(request: Request, endpoint: str | None = None) -> Response:
    from app.core import agent_crypto
    from app.core.forwarded import forwarded_base_url
    from app.db.session import SessionLocal
    from app.services import agent_endpoints, agent_install

    with SessionLocal() as db:
        # Same rule as GET /api/v1/agents/install-command: absent falls back,
        # unknown is refused. The two must agree, because the digest the UI
        # publishes is computed over whatever this route renders.
        if endpoint is None:
            server_url = forwarded_base_url(request)
        else:
            selected = agent_endpoints.find_endpoint(db, endpoint)
            if selected is None:
                raise HTTPException(
                    status_code=404, detail=f"No agent endpoint with id {endpoint!r}"
                )
            server_url = selected["url"]

        cert = agent_install._active_certificate(db)
        tls_mode, tls_pin = agent_install._tls_mode_and_pin(cert)
        # Task 28: same successor-preferred key selection as
        # agent_install.build_install_command — see its comment.
        state = agent_crypto.load_server_key_rotation_state(db)
        server_pub = state.successor_pub if state.successor_pub is not None else state.current_pub
        script = agent_install.render_install_script(
            server_url=server_url,
            server_static_pk_hex=server_pub.hex(),
            tls_pin=tls_pin,
            manifest=agent_install.agent_update.load_manifest(),
        )
    return Response(content=script, media_type="text/x-shellscript")


async def spa_fallback(full_path: str, request: Request) -> Response:
    # API routes must never fall through to the SPA
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")
    # Serve real files from the dist directory (e.g. site.webmanifest, PWA
    # icons) before falling back to the SPA index.html.  Without this check,
    # the browser receives HTML when it requests JSON/binary assets and shows
    # "Manifest: Syntax error" or broken icon errors.
    frontend_dir_resolved = _frontend_dir.resolve()  # type: ignore[union-attr]
    rel_path = PurePosixPath(full_path.lstrip("/"))
    if any(part in (".", "..") for part in rel_path.parts):
        raise HTTPException(status_code=404, detail="Not found")
    if len(rel_path.parts) == 1:
        candidate = _frontend_root_files.get(rel_path.parts[0])
    else:
        candidate = None
    if candidate and candidate.is_file():
        content_type, _ = mimetypes.guess_type(candidate.name)
        return Response(content=candidate.read_bytes(), media_type=content_type)
    index = frontend_dir_resolved / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return Response(status_code=404)


async def root() -> HTMLResponse:
    return HTMLResponse("<h1>Circuit Breaker API</h1><p>Frontend not built.</p>")


def register(app: FastAPI) -> None:
    """Mount static trees and register the SPA fallback, in dependency order.

    Call this after every router is included.  The last route registered is the
    catch-all, and every mount below has to exist before it or it will swallow
    the request.
    """
    app.mount("/uploads", StaticFiles(directory=str(_uploads_dir)), name="uploads")
    app.mount("/user-icons", StaticFiles(directory=str(_user_icons_dir)), name="user-icons")
    app.mount("/branding", StaticFiles(directory=str(_branding_dir_data)), name="branding")
    app.mount("/.well-known/acme-challenge", _AcmeChallengeFiles(), name="acme-challenge")

    app.middleware("http")(_static_cache_middleware)

    app.add_api_route("/favicon.ico", favicon_file, methods=["GET"], include_in_schema=False)
    app.add_api_route(
        "/install-agent.sh", get_install_agent_script, methods=["GET"], include_in_schema=False
    )

    if _frontend_dir:
        _assets = _frontend_dir / "assets"
        if _assets.exists():
            app.mount("/assets", StaticFiles(directory=str(_assets)), name="assets")

        _icons = _frontend_dir / "icons"
        if _icons.exists():
            app.mount("/icons", StaticFiles(directory=str(_icons)), name="icons")

        app.add_api_route(
            "/{full_path:path}",
            spa_fallback,
            methods=["GET"],
            include_in_schema=False,
            responses={404: {"description": "Not found"}},
        )
    else:
        app.add_api_route("/", root, methods=["GET"], include_in_schema=False)
