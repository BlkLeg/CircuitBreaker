from typing import Any

from fastapi import APIRouter

from app.services.catalog_service import (
    fuzzy_search_catalog,
    get_all_vendors,
    get_device_spec,
    get_vendor_devices,
)

router = APIRouter(tags=["catalog"])


@router.get("/vendors")
def list_vendors() -> list[Any]:
    return get_all_vendors()


@router.get("/vendors/{vendor_key}/devices")
def list_devices(vendor_key: str) -> list[Any]:
    return get_vendor_devices(vendor_key)


@router.get("/vendors/{vendor_key}/devices/{model_key}")
def get_device(vendor_key: str, model_key: str) -> dict[str, Any]:
    spec = get_device_spec(vendor_key, model_key)
    if not spec:
        return {}
    return spec


@router.get("/search")
def search_catalog(q: str = "") -> list[Any]:
    """
    Typeahead search. Always returns a freeform fallback as last item.
    """
    return fuzzy_search_catalog(q)
