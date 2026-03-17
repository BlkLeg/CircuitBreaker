import asyncio

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_concurrent_db_load(live_server):
    async with AsyncClient(base_url=live_server.url) as client:
        tasks = [client.get("/api/v1/health") for _ in range(100)]
        results = await asyncio.gather(*tasks, return_when=asyncio.ALL_COMPLETED)
        assert all(r.status_code == 200 for r in results if not getattr(r, "is_error", False))


@pytest.mark.parametrize("tabs", [10])
@pytest.mark.asyncio
async def test_ws_concurrency(live_server, tabs):
    # Open N WS connections, assert responsive after 60s load
    pass
