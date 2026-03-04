import json
from functools import lru_cache
from pathlib import Path

CATALOG_PATH = Path(__file__).parent.parent / "data" / "vendor_catalog.json"


@lru_cache(maxsize=1)
def load_catalog() -> dict:
    with open(CATALOG_PATH) as f:
        return json.load(f)


def get_all_vendors() -> list[dict]:
    catalog = load_catalog()
    return [
        {"key": k, "label": v["label"], "icon": v.get("icon")}
        for k, v in catalog.items()
    ]


def get_vendor_devices(vendor_key: str) -> list[dict]:
    catalog = load_catalog()
    vendor = catalog.get(vendor_key)
    if not vendor:
        return []
    return [
        {"key": k, **v}
        for k, v in vendor.get("devices", {}).items()
    ]


def get_device_spec(vendor_key: str, model_key: str) -> dict | None:
    catalog = load_catalog()
    return catalog.get(vendor_key, {}).get("devices", {}).get(model_key)


def fuzzy_search_catalog(query: str) -> list[dict]:
    """
    Returns matching vendors+devices for typeahead.
    Always appends a freeform fallback option as the last result.
    """
    catalog = load_catalog()
    query_lower = query.lower()
    results = []

    for vendor_key, vendor in catalog.items():
        for model_key, device in vendor.get("devices", {}).items():
            if (query_lower in device["label"].lower() or
                    query_lower in vendor["label"].lower() or
                    query_lower in model_key):
                results.append({
                    "vendor_key": vendor_key,
                    "model_key": model_key,
                    "vendor_label": vendor["label"],
                    "device_label": device["label"],
                    "icon": vendor.get("icon"),
                    "u_height": device.get("u_height", 1),
                    "role": device.get("role"),
                    "telemetry_profile": device.get("telemetry_profile"),
                })

    # Always append the freeform fallback
    results.append({
        "vendor_key": None,
        "model_key": None,
        "vendor_label": None,
        "device_label": query,
        "icon": None,
        "u_height": 1,
        "role": None,
        "telemetry_profile": None,
        "_freeform": True,
    })

    return results
