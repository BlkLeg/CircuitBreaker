from typing import Any

from fastapi import APIRouter

from app.services.catalog_service import (
    fuzzy_search_catalog,
    get_all_vendors,
    get_vendor_devices,
)

router = APIRouter(tags=["catalog"])


@router.get("/vendors")
def list_vendors() -> list[Any]:
    return get_all_vendors()


@router.get("/vendors/{vendor_key}/devices")
def list_devices(vendor_key: str) -> list[Any]:
    return get_vendor_devices(vendor_key)


@router.get("/search")
def search_catalog(q: str = "") -> list[Any]:
    """
    Typeahead search. Always returns a freeform fallback as last item.
    """
    return fuzzy_search_catalog(q)
