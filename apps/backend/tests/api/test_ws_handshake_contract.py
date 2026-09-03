"""The WebSocket session check is one sequence, pinned here.

Four stream endpoints each carried an identical copy of this logic, nested five
conditionals deep (route F10). Copies drift silently: the check most easily lost
is the expired-demo one at the bottom, and losing it means a demo account whose
window closed keeps a live stream open indefinitely — which no test anywhere
would have caught.

So each refusal reason gets its own case. A shared helper only stays correct if
something fails when one of its branches disappears.

These test the helper directly rather than through five socket handshakes: the
sockets differ in what they do *after* authentication, and driving them would
test the manager, the CIDR gate and the connection cap alongside the one thing
under test here.
"""

from __future__ import annotations

import pathlib
from datetime import timedelta

import pytest

from app.api.ws_session import resolve_ws_session_user
from app.core.security import create_token
from app.core.time import utcnow
from app.services.settings_service import get_or_create_settings


def _token_for(db, user) -> str:
    cfg = get_or_create_settings(db)
    return create_token(user.id, cfg.jwt_secret, 8)


def test_a_valid_session_token_resolves_its_user(db_session, factories) -> None:
    user = factories.user(role="admin")
    db_session.commit()

    resolved = resolve_ws_session_user(db_session, _token_for(db_session, user))

    assert resolved is not None
    assert resolved.id == user.id


def test_an_empty_token_is_refused(db_session) -> None:
    assert resolve_ws_session_user(db_session, "") is None


def test_a_forged_alg_none_token_is_refused(db_session) -> None:
    """`decode_token` pins HS256 and the audience; this is what that buys."""
    forged = "eyJhbGciOiJub25lIn0.eyJ1c2VyX2lkIjoxfQ."

    assert resolve_ws_session_user(db_session, forged) is None


def test_a_token_signed_with_the_wrong_secret_is_refused(db_session, factories) -> None:
    user = factories.user()
    db_session.commit()
    wrong = create_token(user.id, "not-the-configured-secret-but-long-enough-x", 8)

    assert resolve_ws_session_user(db_session, wrong) is None


def test_an_inactive_user_is_refused(db_session, factories) -> None:
    user = factories.user()
    token = _token_for(db_session, user)
    user.is_active = False
    db_session.commit()

    assert resolve_ws_session_user(db_session, token) is None


def test_a_locked_user_is_refused_while_the_lock_holds(db_session, factories) -> None:
    user = factories.user()
    token = _token_for(db_session, user)
    user.locked_until = utcnow() + timedelta(hours=1)
    db_session.commit()

    assert resolve_ws_session_user(db_session, token) is None


def test_a_lock_that_has_expired_does_not_refuse(db_session, factories) -> None:
    """A stale lock must not lock a user out permanently."""
    user = factories.user()
    token = _token_for(db_session, user)
    user.locked_until = utcnow() - timedelta(hours=1)
    db_session.commit()

    assert resolve_ws_session_user(db_session, token) is not None


def test_an_expired_demo_account_is_refused(db_session, factories) -> None:
    """The branch most easily lost when this block is copied between streams.

    A demo whose window has closed keeping a live stream open is exactly the
    kind of quiet authorization leak that survives for releases.
    """
    user = factories.user(role="demo")
    token = _token_for(db_session, user)
    user.demo_expires = utcnow() - timedelta(minutes=1)
    db_session.commit()

    assert resolve_ws_session_user(db_session, token) is None


def test_a_demo_account_still_inside_its_window_is_allowed(db_session, factories) -> None:
    user = factories.user(role="demo")
    token = _token_for(db_session, user)
    user.demo_expires = utcnow() + timedelta(minutes=30)
    db_session.commit()

    assert resolve_ws_session_user(db_session, token) is not None


@pytest.mark.parametrize(
    "module_name",
    [
        "app.api.ws_topology",
        "app.api.ws_telemetry",
        "app.api.ws_discovery",
        "app.api.ws_agents",
    ],
)
def test_every_adopting_stream_goes_through_the_shared_helper(module_name: str) -> None:
    """Adoption is the point; a stream that quietly reverts must fail here.

    `ws_monitors` is intentionally absent: it authenticates more identity kinds
    than this helper covers (service-account JWTs, API tokens) and collapsing it
    in would either widen these four or narrow that one. See `ws_session`.
    """
    import ast
    import importlib

    source_path = importlib.import_module(module_name).__file__
    assert source_path is not None
    source = pathlib.Path(source_path).read_text(encoding="utf-8")
    tree = ast.parse(source)

    # Parsed rather than grepped. The substring version of this test asserted
    # that the string "resolve_ws_session_user" appeared *somewhere* in the file
    # and that "decode_token(" did not. Both pass on a stream that re-inlines a
    # weaker handshake with `jwt.decode(...)` — a different spelling — while
    # leaving one stale mention of the helper behind in a comment or an unused
    # import. The gate would have been green through the exact reversion it
    # exists to catch, which is F10 with extra steps.
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    called_attrs = {
        f"{node.func.value.id}.{node.func.attr}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
    }

    assert "resolve_ws_session_user" in called, (
        f"{module_name} no longer *calls* the shared session check — a re-inlined "
        "copy is how the expired-demo branch gets lost. An import or a mention in "
        "a comment is not adoption"
    )

    # Every way a stream could decode a token for itself again, rather than the
    # one spelling the old assertion happened to name.
    forbidden = {"decode_token", "jwt.decode", "jose.decode", "jwt.get_unverified_claims"}
    reinlined = forbidden & (called | called_attrs)
    assert not reinlined, (
        f"{module_name} decodes tokens itself again ({sorted(reinlined)}); that is "
        "the duplication F10 is about. Route it through app.api.ws_session"
    )
