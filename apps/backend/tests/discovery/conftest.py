"""Package-local fixtures for tests/discovery/.

`cancel_frames` is used by both test_cancellation.py and test_pause_resume.py.
It is a pytest fixture rather than a plain helper, so it belongs here rather
than in helpers.py — see that module's docstring. This file is scoped to
tests/discovery/ only; it does not touch the top-level tests/conftest.py.
"""

import pytest


@pytest.fixture
def cancel_frames(monkeypatch):
    """Every control frame a cancellation would put on the wire."""
    from unittest.mock import AsyncMock

    from app.services import agent_registry

    frames: list[tuple[int, dict]] = []

    async def _spy(agent_id: int, frame: dict) -> bool:
        frames.append((agent_id, frame))
        return True

    monkeypatch.setattr(agent_registry, "publish_agent_control_frame", AsyncMock(side_effect=_spy))
    return frames
