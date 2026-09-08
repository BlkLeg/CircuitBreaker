"""HTTP contracts for paged inventory and selectors."""

import pytest


@pytest.mark.asyncio
async def test_hardware_page_preserves_legacy_list_and_returns_envelope(
    client, auth_headers, factories
):
    factories.hardware(name="Zulu page host")
    factories.hardware(name="Alpha page host")

    legacy = await client.get("/api/v1/hardware", headers=auth_headers)
    page = await client.get(
        "/api/v1/hardware/page",
        params={"limit": 1, "sort": "name", "direction": "asc", "q": "page host"},
        headers=auth_headers,
    )

    assert legacy.status_code == 200
    assert isinstance(legacy.json(), list)
    assert page.status_code == 200, page.text
    assert page.json()["total"] == 2
    assert page.json()["items"][0]["name"] == "Alpha page host"
    assert page.json()["limit"] == 1


@pytest.mark.asyncio
async def test_inventory_options_support_aliases_and_missing_selected_values(
    client, auth_headers, factories
):
    hardware = factories.hardware(name="Compute host")
    compute = factories.compute_unit(name="Docker parent", hardware_id=hardware.id)

    response = await client.get(
        "/api/v1/inventory/options",
        params=[
            ("action", "docker_parent"),
            ("types", "compute"),
            ("q", "Docker"),
            ("selected", f"compute:{compute.id}"),
            ("selected", "compute:999999"),
        ],
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["items"][0]["ref"] == {
        "entity_type": "compute_unit",
        "entity_id": compute.id,
        "key": f"compute_unit:{compute.id}",
    }
    assert data["selected"][1]["unavailable_reason"] == "not_found"


@pytest.mark.asyncio
async def test_inventory_options_reject_ineligible_type(client, auth_headers):
    response = await client.get(
        "/api/v1/inventory/options",
        params={"action": "docker_parent", "types": "service"},
        headers=auth_headers,
    )

    assert response.status_code == 422
