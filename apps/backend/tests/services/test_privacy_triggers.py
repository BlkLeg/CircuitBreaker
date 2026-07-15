"""Scan-finalize privacy hook: fires recompute, and its failures never propagate."""

from unittest.mock import AsyncMock, patch

import pytest

from app.services import discovery_service


@pytest.mark.asyncio
async def test_privacy_recompute_hook_invokes_recompute_all():
    recompute = AsyncMock(return_value={"score": 100})
    with patch("app.services.privacy_score.recompute_all", recompute):
        await discovery_service._run_privacy_recompute()
    recompute.assert_awaited_once()


@pytest.mark.asyncio
async def test_privacy_recompute_hook_swallows_scoring_errors():
    recompute = AsyncMock(side_effect=RuntimeError("scoring bug"))
    with patch("app.services.privacy_score.recompute_all", recompute):
        # must not raise — a scoring bug can never fail a discovery scan
        await discovery_service._run_privacy_recompute()
    recompute.assert_awaited_once()


@pytest.mark.asyncio
async def test_schedule_privacy_recompute_is_fire_and_forget():
    recompute = AsyncMock(return_value=None)
    with patch("app.services.privacy_score.recompute_all", recompute):
        discovery_service._schedule_privacy_recompute()
        # give the scheduled task a tick to run
        import asyncio

        await asyncio.sleep(0)
        await asyncio.sleep(0.01)
    recompute.assert_awaited_once()
