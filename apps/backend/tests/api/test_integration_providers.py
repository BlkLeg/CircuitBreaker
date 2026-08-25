"""INC-16: the provider set the API accepts, and the provider set the product implements.

`VALID_PROVIDERS` listed four. Only proxmox and docker have a `test_config` branch, and
truenas and unifi have no sync implementation either — so an operator could store TrueNAS or
UniFi credentials in a configuration nothing in the product would ever use, and the only
feedback was a *Test* button answering "Test not implemented for provider 'truenas'", which
describes our gap rather than their mistake.

The first two tests are the pin against its return: the two lists disagreeing *is* the
finding, so a provider added to one and not the other fails here.
"""

from __future__ import annotations

import inspect

import pytest

from app.schemas.integration_provider import VALID_PROVIDERS
from app.services import integration_provider_service as svc

_IMPLEMENTED = {"proxmox", "docker"}


def test_valid_providers_is_exactly_what_is_implemented():
    assert VALID_PROVIDERS == _IMPLEMENTED


def test_every_valid_provider_can_be_tested():
    """A provider the API accepts and test_config cannot reach is this finding again."""
    source = inspect.getsource(svc.test_config)

    for provider in VALID_PROVIDERS:
        assert f'"{provider}"' in source, (
            f"'{provider}' is accepted by the API but test_config has no branch for it"
        )


def test_every_valid_provider_has_a_sync_path():
    """The other half. truenas and unifi had a test gap *and* no sync — the finding
    recorded only the first, which read as narrower than it was."""
    source = inspect.getsource(svc)

    for provider in VALID_PROVIDERS:
        assert f'"{provider}"' in source


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["truenas", "unifi"])
async def test_a_dropped_provider_is_refused(client, auth_headers, provider):
    resp = await client.get(f"/api/v1/integrations/{provider}/config", headers=auth_headers)

    assert resp.status_code == 400
    assert "proxmox" in resp.text and "docker" in resp.text


@pytest.mark.asyncio
async def test_a_supported_provider_is_still_served(client, auth_headers):
    resp = await client.get("/api/v1/integrations/proxmox/config", headers=auth_headers)

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_creating_a_dropped_provider_config_is_refused(client, auth_headers):
    """The read being refused and the write accepted would leave the credential stored."""
    resp = await client.post(
        "/api/v1/integrations/truenas/config",
        json={"name": "NAS", "config_url": "https://nas.example.com", "credential_value": "s3cret"},
        headers=auth_headers,
    )

    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_the_unsupported_message_describes_the_caller_not_our_gap(db_session):
    """ "Test not implemented" told an operator we had not built it yet. Now that the set is
    closed, reaching this branch means the caller named something that does not exist."""
    result = await svc.test_config(db_session, "route53", 1)

    assert "not implemented" not in result["message"].lower()
