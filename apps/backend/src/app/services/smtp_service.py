"""SMTP email delivery service.

Provides async helpers for testing SMTP connectivity, sending invite emails,
and sending password-reset emails.  Passwords are stored encrypted via
CredentialVault; this service never handles plaintext credentials beyond the
moment of decryption for the SMTP login call.
"""

from __future__ import annotations

import logging
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

try:
    import aiosmtplib
except ImportError:  # pragma: no cover - exercised in runtime fallback paths
    aiosmtplib = None

from app.services.credential_vault import get_vault

if TYPE_CHECKING:
    from app.db.models import AppSettings

_log = logging.getLogger(__name__)

# Baked into the backend image by backend.Dockerfile — always available.
_DEFAULT_LOGO = Path("/app/default-logo.png")

# MIME subtypes for supported logo formats.  SVG is excluded intentionally:
# most email clients cannot render SVG attachments via CID.
_LOGO_MIME: dict[str, str] = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".gif": "gif"}


def _require_aiosmtplib():
    if aiosmtplib is None:
        raise RuntimeError(
            "SMTP support is unavailable because `aiosmtplib` is not installed. "
            "Rebuild the backend image after updating dependencies."
        )
    return aiosmtplib


def resolve_public_base_url(cfg: AppSettings, fallback_base_url: str | None = None) -> str:
    """Return the externally reachable app base URL for emails."""
    configured = (getattr(cfg, "api_base_url", None) or "").strip()
    candidate = configured or (fallback_base_url or "").strip()
    if not candidate:
        return ""

    if "://" not in candidate:
        candidate = f"https://{candidate}"

    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return (fallback_base_url or "").rstrip("/")
    return candidate.rstrip("/")


def public_base_from_request_headers(headers: object, fallback_base_url: str = "") -> str:
    """Extract the externally reachable base URL from proxy/request headers.

    Prefers X-Forwarded-Host > Host over the raw fallback so that links in
    emails use the correct public hostname even when api_base_url is unset.
    Works with any headers mapping (e.g. Starlette Headers).
    """
    host = headers.get("x-forwarded-host") or headers.get("host", "")  # type: ignore[attr-defined]
    if host:
        proto = headers.get("x-forwarded-proto", "https")  # type: ignore[attr-defined]
        # X-Forwarded-Host may be a comma-separated list; take the first entry.
        return f"{proto}://{host.split(',')[0].strip()}"
    return fallback_base_url.rstrip("/")


def _resolve_logo_path(cfg: AppSettings) -> Path | None:
    """Return an absolute Path to the logo file, or None if unavailable.

    Resolution order:
    1. Custom logo uploaded via Settings → Branding (stored under uploads_dir)
    2. Default Circuit Breaker logo baked into the Docker image
    """
    from app.core.config import settings as _app_cfg  # local import avoids circular

    logo_db_path = getattr(cfg, "login_logo_path", None)
    if logo_db_path:
        # login_logo_path is a URL path like "/branding/login-logo.png";
        # strip the leading "/" and resolve against the uploads dir.
        candidate = Path(_app_cfg.uploads_dir) / logo_db_path.lstrip("/")
        ext = candidate.suffix.lower()
        if candidate.exists() and ext in _LOGO_MIME:
            return candidate

    if _DEFAULT_LOGO.exists():
        return _DEFAULT_LOGO

    return None


class SmtpService:
    """Thin async wrapper around aiosmtplib for Circuit Breaker email delivery."""

    def __init__(self, cfg: AppSettings) -> None:
        self.cfg = cfg

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _password(self) -> str:
        if self.cfg.smtp_password_enc:
            try:
                return get_vault().decrypt(self.cfg.smtp_password_enc)
            except Exception as exc:
                _log.warning(
                    "Failed to decrypt SMTP password (CB_VAULT_KEY may have changed "
                    "since the password was saved — re-save it in Settings): %s",
                    exc,
                )
        return ""

    async def _connect(self) -> aiosmtplib.SMTP:
        smtp_lib = _require_aiosmtplib()
        # aiosmtplib 3.x: start_tls defaults to None (auto), which causes
        # connect() to transparently upgrade the socket when the server
        # advertises STARTTLS — even on port 587.  If we then call starttls()
        # manually we hit "Connection already using TLS".  Setting start_tls=False
        # disables the automatic upgrade so we can control TLS explicitly.
        #
        # Port 465  → implicit/SSL TLS: use_tls=True, no starttls() call.
        # Port 587  → STARTTLS: plain connect, then starttls() when smtp_tls=True.
        # Port 25   → plain SMTP: no TLS at all.
        use_implicit_tls = self.cfg.smtp_port == 465
        smtp = smtp_lib.SMTP(
            hostname=self.cfg.smtp_host,
            port=self.cfg.smtp_port,
            use_tls=use_implicit_tls,
            start_tls=False,  # never auto-upgrade; we handle STARTTLS below
            timeout=30,
        )
        await smtp.connect()
        if self.cfg.smtp_tls and not use_implicit_tls:
            await smtp.starttls()
        if self.cfg.smtp_username:
            await smtp.login(self.cfg.smtp_username, self._password())
        return smtp

    def _build_message(
        self, to_email: str, subject: str, html: str, logo_path: Path | None = None
    ) -> MIMEMultipart:
        """Build a MIME message.

        When *logo_path* is provided the message uses multipart/related so the
        logo is embedded as an inline CID attachment (``cid:cb-email-logo``).
        This avoids broken-image icons in Gmail and other clients that cannot
        reach private LAN hostnames like ``circuitbreaker.local``.
        """
        if logo_path and logo_path.exists():
            ext = logo_path.suffix.lower()
            subtype = _LOGO_MIME.get(ext)
            if subtype:
                outer = MIMEMultipart("related")
                outer["Subject"] = subject
                outer["From"] = f"{self.cfg.smtp_from_name} <{self.cfg.smtp_from_email}>"
                outer["To"] = to_email
                outer.attach(MIMEText(html, "html", "utf-8"))
                img = MIMEImage(logo_path.read_bytes(), _subtype=subtype)
                img.add_header("Content-ID", "<cb-email-logo>")
                img.add_header("Content-Disposition", "inline", filename=f"logo{ext}")
                outer.attach(img)
                return outer

        # Fallback when no logo is available or format is unsupported (e.g. SVG)
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{self.cfg.smtp_from_name} <{self.cfg.smtp_from_email}>"
        msg["To"] = to_email
        msg.attach(MIMEText(html, "html", "utf-8"))
        return msg

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def _branding(self) -> tuple[str, str, Path | None]:
        """Return (app_name, primary_color, logo_path) for email rendering."""
        app_name = getattr(self.cfg, "app_name", None) or "Circuit Breaker"
        primary_color = getattr(self.cfg, "primary_color", None) or "#fe8019"
        return app_name, primary_color, _resolve_logo_path(self.cfg)

    async def test_connection(self) -> dict:
        """Open an SMTP connection, optionally STARTTLS + login, then quit."""
        try:
            smtp = await self._connect()
            await smtp.quit()
            return {"status": "ok", "message": "Connection successful"}
        except Exception as exc:
            _log.warning("SMTP test failed: %s", exc)
            return {"status": "error", "message": str(exc)}

    async def send_test_email(self, to_email: str, base_url: str | None = None) -> dict:
        """Send a simple test message to verify end-to-end delivery."""
        try:
            app_name, primary_color, logo_path = self._branding()
            smtp = await self._connect()
            msg = self._build_message(
                to_email,
                f"[Test] {app_name} SMTP",
                _test_html(app_name, primary_color, logo_path is not None),
                logo_path=logo_path,
            )
            await smtp.send_message(msg, sender=self.cfg.smtp_from_email)
            await smtp.quit()
            return {"status": "ok", "message": f"Test email sent to {to_email}"}
        except Exception as exc:
            _log.warning("SMTP test email failed: %s", exc)
            return {"status": "error", "message": str(exc)}

    async def send_invite(self, to_email: str, token: str, invited_by: str, base_url: str) -> None:
        """Send an invite email with a clickable accept link."""
        app_name, primary_color, logo_path = self._branding()
        invite_url = f"{base_url}/invite/accept?token={token}"
        smtp = await self._connect()
        msg = self._build_message(
            to_email,
            f"You've been invited to {app_name}",
            _invite_html(app_name, primary_color, logo_path is not None, invited_by, invite_url),
            logo_path=logo_path,
        )
        await smtp.send_message(msg, sender=self.cfg.smtp_from_email)
        await smtp.quit()

    async def send_password_reset(self, to_email: str, token: str, base_url: str) -> None:
        """Send a password-reset email with a clickable reset link."""
        app_name, primary_color, logo_path = self._branding()
        reset_url = f"{base_url}/reset-password?token={token}"
        smtp = await self._connect()
        msg = self._build_message(
            to_email,
            f"Password reset — {app_name}",
            _reset_html(app_name, primary_color, logo_path is not None, reset_url),
            logo_path=logo_path,
        )
        await smtp.send_message(msg, sender=self.cfg.smtp_from_email)
        await smtp.quit()


# ---------------------------------------------------------------------------
# Email HTML templates — all styles are inlined.
#
# Gmail and most email clients strip <style> blocks, so class-based CSS is
# unreliable.  Every element carries its own style="" attribute so the email
# looks correct regardless of the mail client.
# ---------------------------------------------------------------------------

# Shared inline-style constants
_S_WRAP = "max-width:560px;margin:40px auto;background:#282828;border-radius:10px;overflow:hidden;font-family:Arial,sans-serif"
_S_BODY = "padding:32px 36px;background:#282828"
_S_P = "margin:0 0 16px;line-height:1.65;color:#d5c4a1;font-size:15px"
_S_SMALL = "font-size:13px;color:#928374;margin:0"
_S_HR = "border:none;border-top:1px solid #3c3836;margin:24px 0"
_S_FOOT = "padding:18px 32px;background:#1d2021;font-size:12px;color:#928374;text-align:center;font-family:Arial,sans-serif"


def _s_header(primary_color: str) -> str:
    return f"background:{primary_color};padding:28px 32px;text-align:center"


def _s_btn(primary_color: str) -> str:
    return (
        f"display:inline-block;margin:16px 0;padding:13px 30px;"
        f"background:{primary_color};color:#1d2021;border-radius:6px;"
        f"text-decoration:none;font-weight:700;font-size:15px"
    )


def _header_block(app_name: str, primary_color: str, has_logo: bool) -> str:
    """Render the branded email header.

    When *has_logo* is True the ``<img>`` references ``cid:cb-email-logo``, which
    is resolved by the MIMEImage attachment added in ``_build_message``.  This
    approach works in every major email client (Gmail, Outlook, Apple Mail) without
    needing an externally reachable URL.
    """
    s = _s_header(primary_color)
    if has_logo:
        img = (
            f'<img src="cid:cb-email-logo" alt="{app_name}" '
            f'style="max-height:56px;max-width:220px;display:block;margin:0 auto;border:0">'
        )
        h1 = (
            f'<h1 style="margin:8px 0 0;font-size:18px;color:#1d2021;'
            f'letter-spacing:.4px;font-weight:700;font-family:Arial,sans-serif">{app_name}</h1>'
        )
        return f'<div style="{s}">{img}{h1}</div>'
    h1 = (
        f'<h1 style="margin:0;font-size:20px;color:#1d2021;'
        f'letter-spacing:.4px;font-weight:700;font-family:Arial,sans-serif">{app_name}</h1>'
    )
    return f'<div style="{s}">{h1}</div>'


def _invite_html(
    app_name: str, primary_color: str, has_logo: bool, invited_by: str, invite_url: str
) -> str:
    header = _header_block(app_name, primary_color, has_logo)
    btn = _s_btn(primary_color)
    return (
        f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"></head>'
        f'<body style="margin:0;padding:0;background:#1d2021">'
        f'<div style="{_S_WRAP}">'
        f"  {header}"
        f'  <div style="{_S_BODY}">'
        f'    <p style="{_S_P}">Hi there,</p>'
        f'    <p style="{_S_P}"><strong>{invited_by}</strong> has invited you to join'
        f"    <strong>{app_name}</strong>.</p>"
        f'    <p style="{_S_P}">Click the button below to create your account.'
        f"    This link expires in&nbsp;7&nbsp;days.</p>"
        f'    <a href="{invite_url}" style="{btn}">Accept Invite &rarr;</a>'
        f'    <hr style="{_S_HR}">'
        f'    <p style="{_S_SMALL}">Or copy this link into your browser:<br>'
        f'    <a href="{invite_url}" style="color:#a89984;word-break:break-all">{invite_url}</a></p>'
        f"  </div>"
        f'  <div style="{_S_FOOT}">'
        f"    You received this because an admin invited you to {app_name}."
        f"    If you weren&rsquo;t expecting this, you can safely ignore it."
        f"  </div>"
        f"</div>"
        f"</body></html>"
    )


def _reset_html(app_name: str, primary_color: str, has_logo: bool, reset_url: str) -> str:
    header = _header_block(app_name, primary_color, has_logo)
    btn = _s_btn(primary_color)
    return (
        f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"></head>'
        f'<body style="margin:0;padding:0;background:#1d2021">'
        f'<div style="{_S_WRAP}">'
        f"  {header}"
        f'  <div style="{_S_BODY}">'
        f'    <p style="{_S_P}">Hi there,</p>'
        f'    <p style="{_S_P}">A password reset was requested for your'
        f"    <strong>{app_name}</strong> account.</p>"
        f'    <p style="{_S_P}">Click the button below to choose a new password.'
        f"    This link expires in&nbsp;1&nbsp;hour.</p>"
        f'    <a href="{reset_url}" style="{btn}">Reset Password &rarr;</a>'
        f'    <hr style="{_S_HR}">'
        f'    <p style="{_S_SMALL}">If you didn&rsquo;t request this, you can safely'
        f"    ignore this email &mdash; your password has not been changed.</p>"
        f"  </div>"
        f'  <div style="{_S_FOOT}">{app_name} &mdash; automated security notification</div>'
        f"</div>"
        f"</body></html>"
    )


def _test_html(app_name: str, primary_color: str, has_logo: bool) -> str:
    header = _header_block(app_name, primary_color, has_logo)
    return (
        f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"></head>'
        f'<body style="margin:0;padding:0;background:#1d2021">'
        f'<div style="{_S_WRAP}">'
        f"  {header}"
        f'  <div style="{_S_BODY}">'
        f'    <p style="{_S_P}">This is a test email from <strong>{app_name}</strong>.</p>'
        f'    <p style="{_S_P}">If you received this, your SMTP configuration is working correctly.</p>'
        f"  </div>"
        f'  <div style="{_S_FOOT}">{app_name} &mdash; SMTP test</div>'
        f"</div>"
        f"</body></html>"
    )
