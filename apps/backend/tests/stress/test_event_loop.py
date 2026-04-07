import asyncio

import pytest


@pytest.mark.asyncio
async def test_concurrent_db_load(client):
    tasks = [client.get("/api/v1/health") for _ in range(100)]
    results = await asyncio.gather(*tasks)
    assert all(r.status_code == 200 for r in results)


@pytest.mark.parametrize("parallelism", [25])
@pytest.mark.asyncio
async def test_event_loop_burst_health(client, parallelism):
    """ASGI app stays responsive under a burst of concurrent HTTP requests."""

    async def one() -> int:
        r = await client.get("/api/v1/health")
        return r.status_code

    codes = await asyncio.gather(*[one() for _ in range(parallelism)])
    assert all(c == 200 for c in codes)
