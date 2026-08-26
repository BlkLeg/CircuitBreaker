"""Four discovery write routes were reachable by any viewer.

`api/discovery.py` mounts its router with `dependencies=[require_scope("read", "*")]`,
and these four routes each declared `_user=require_write_auth` — as a bare default
rather than `Depends(require_write_auth)`. FastAPI treats a non-`Depends` default as an
ordinary parameter default, so the dependency was never called and the only gate left
standing was the router's read scope, which every viewer satisfies. The docstrings said
"Requires write role" throughout.

They are not read routes: `batch-import` and `import-as-network` create `Hardware` rows
and topology, `lldp-enrich` enqueues a job that writes to them, and `lldp-jobs/{id}/apply`
rewrites `Hardware` and `HardwareConnection`.

`test_no_write_route_is_merely_authenticated` is the structural half of this and now
fails when the `Depends(...)` is removed. These cases are the behavioural half: they
assert the response a viewer actually receives, which no structural gate can prove.
"""

from __future__ import annotations

import pytest

# A viewer must be refused before the body is ever read, so the payloads only need to be
# shaped well enough to reach authorization. A 422 here would mean the gate let them past.
_WRITE_ROUTES = [
    ("/api/v1/discovery/jobs/1/batch-import", {"result_ids": [1]}),
    ("/api/v1/discovery/jobs/1/import-as-network", {"result_ids": [1]}),
    ("/api/v1/discovery/lldp-enrich", {"hardware_ids": [1]}),
    ("/api/v1/discovery/lldp-jobs/1/apply", {"neighbor_ids": [1]}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("path,payload", _WRITE_ROUTES)
async def test_viewer_cannot_call_a_discovery_write_route(client, viewer_headers, path, payload):
    resp = await client.post(path, json=payload, headers=viewer_headers)

    assert resp.status_code == 403, (
        f"{path} answered {resp.status_code} to a viewer; a write route must refuse one"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("path,payload", _WRITE_ROUTES)
async def test_an_editor_gets_past_authorization_on_a_discovery_write_route(
    client, editor_headers, path, payload
):
    """The gate must not have been tightened into a wall.

    An editor holds write, so authorization must pass. What the route then does with a
    job id that does not exist is its own business — 404 and 422 both mean the request
    was authorized, which is the whole of the claim here.
    """
    resp = await client.post(path, json=payload, headers=editor_headers)

    assert resp.status_code not in (401, 403), (
        f"{path} refused an editor with {resp.status_code}; editors hold write"
    )
