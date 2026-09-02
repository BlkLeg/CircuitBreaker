"""The one WebSocket session-token check, shared by the stream endpoints.

Route F10 describes this as "WS auth duplication" and points at `ws_monitors`
doing a "raw `jwt.decode`". Measured against the code, that framing is backwards
and the correction matters for what this module is allowed to do.

`ws_topology`, `ws_telemetry`, `ws_discovery` and `ws_agents` each carried a
byte-for-byte-equivalent copy of the block below — decode, revocation, active,
not locked, not an expired demo — nested five conditionals deep. **That** is the
duplication, and it is what this function replaces.

`ws_monitors` is the outlier in the other direction: its `jwt.decode` is
correctly pinned to HS256 and the session audience, and it accepts strictly more
identity kinds (service-account JWTs gated on token liveness, stored API tokens)
plus a `read:*` scope check the other four never perform. It is deliberately
**not** collapsed into this helper. Doing so would force one of two bad trades:
widen the four streams to accept API tokens — a privilege change wearing a
refactor's clothes — or narrow `ws_monitors` and drop identity kinds operators
already rely on. A shared core the richer endpoint can build on is the honest
shape; a superset is not.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.core.time import utcnow
from app.db.models import User
from app.services.settings_service import get_or_create_settings
from app.services.user_service import is_session_revoked


def resolve_ws_session_user(db: Session, raw_token: str) -> User | None:
    """The user a first-message session token authorizes, or `None`.

    Every reason to refuse returns `None` rather than raising: the callers all
    respond to a failed handshake identically — send `{"error": "unauthorized"}`
    and close with 1008 — and a helper that raised would push exception handling
    into five socket loops for no gain.

    The refusals, in the order they are checked:

    - **No configured JWT secret.** Nothing can be verified, so nothing is
      trusted.
    - **Revoked session.** Checked before decoding, so a revoked-but-unexpired
      token is refused without its claims ever being read.
    - **Undecodable token.** `decode_token` pins HS256 and the session audience,
      which is what makes an `alg=none` forgery fail here.
    - **Unknown or inactive user.**
    - **Locked user**, while the lock is still in force.
    - **Expired demo account.** A demo whose window has closed is not a valid
      session, and this is the check most easily lost when the block is copied.
    """
    cfg = get_or_create_settings(db)
    if not cfg.jwt_secret or not raw_token:
        return None
    if is_session_revoked(db, raw_token):
        return None

    user_id = decode_token(raw_token, cfg.jwt_secret)
    if user_id is None:
        return None

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        return None
    if user.locked_until and user.locked_until > utcnow():
        return None
    if user.role == "demo" and user.demo_expires and user.demo_expires <= utcnow():
        return None
    return user
