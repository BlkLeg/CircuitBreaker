import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import cast

from app.db import duckdb_client

CATALOG_PATH = Path(__file__).parent.parent / "data" / "vendor_catalog.json"
_logger = logging.getLogger(__name__)

_DUCKDB_CATALOG_LOADED = False


@lru_cache(maxsize=1)
def load_catalog() -> dict:
    with open(CATALOG_PATH) as f:
        return cast(dict, json.load(f))


def _ensure_duckdb_catalog() -> bool:
    """Populate the DuckDB ``vendor_catalog`` table from the JSON file if needed.

    Returns ``True`` when the analytics table is ready for queries.
    """
    global _DUCKDB_CATALOG_LOADED
    if _DUCKDB_CATALOG_LOADED:
        return True
    if not duckdb_client.is_available():
        return False
    try:
        rows = duckdb_client.query(
            "SELECT count(*) AS cnt FROM information_schema.tables "
            "WHERE table_name = 'vendor_catalog'"
        )
        if rows and rows[0]["cnt"] > 0:
            _DUCKDB_CATALOG_LOADED = True
            return True

        catalog = load_catalog()
        duckdb_client.execute(
            "CREATE TABLE vendor_catalog ("
            "  vendor_key TEXT, vendor_label TEXT, vendor_icon TEXT,"
            "  model_key TEXT, device_label TEXT, u_height INTEGER,"
            "  role TEXT, telemetry_profile TEXT"
            ")"
        )
        for vk, vendor in catalog.items():
            for mk, device in vendor.get("devices", {}).items():
                duckdb_client.execute(
                    "INSERT INTO vendor_catalog VALUES (:vk, :vl, :vi, :mk, :dl, :uh, :role, :tp)",
                    {
                        "vk": vk,
                        "vl": vendor["label"],
                        "vi": vendor.get("icon"),
                        "mk": mk,
                        "dl": device["label"],
                        "uh": device.get("u_height", 1),
                        "role": device.get("role"),
                        "tp": device.get("telemetry_profile"),
                    },
                )
        _DUCKDB_CATALOG_LOADED = True
        _logger.info("DuckDB vendor_catalog table populated")
        return True
    except Exception:
        _logger.debug("Failed to populate DuckDB catalog", exc_info=True)
        return False


def get_all_vendors() -> list[dict]:
    catalog = load_catalog()
    return [{"key": k, "label": v["label"], "icon": v.get("icon")} for k, v in catalog.items()]


def get_vendor_devices(vendor_key: str) -> list[dict]:
    catalog = load_catalog()
    vendor = catalog.get(vendor_key)
    if not vendor:
        return []
    return [{"key": k, **v} for k, v in vendor.get("devices", {}).items()]


def get_device_spec(vendor_key: str, model_key: str) -> dict | None:
    catalog = load_catalog()
    return cast(dict | None, catalog.get(vendor_key, {}).get("devices", {}).get(model_key))


def fuzzy_search_catalog(query: str) -> list[dict]:
    """Return matching vendors+devices for typeahead.

    When DuckDB is available the search runs against the analytics engine;
    otherwise it falls back to an in-memory scan of the JSON catalog.
    Always appends a freeform fallback option as the last result.
    """
    if _ensure_duckdb_catalog():
        return _fuzzy_search_duckdb(query)
    return _fuzzy_search_json(query)


def _fuzzy_search_duckdb(query: str) -> list[dict]:
    pattern = f"%{query}%"
    rows = duckdb_client.query(
        "SELECT vendor_key, model_key, vendor_label, device_label, "
        "       vendor_icon AS icon, u_height, role, telemetry_profile "
        "FROM vendor_catalog "
        "WHERE lower(device_label) LIKE lower(:q) "
        "   OR lower(vendor_label) LIKE lower(:q) "
        "   OR lower(model_key) LIKE lower(:q)",
        {"q": pattern},
    )
    results = list(rows)
    results.append(
        {
            "vendor_key": None,
            "model_key": None,
            "vendor_label": None,
            "device_label": query,
            "icon": None,
            "u_height": 1,
            "role": None,
            "telemetry_profile": None,
            "_freeform": True,
        }
    )
    return results


def _fuzzy_search_json(query: str) -> list[dict]:
    catalog = load_catalog()
    query_lower = query.lower()
    results = []

    for vendor_key, vendor in catalog.items():
        for model_key, device in vendor.get("devices", {}).items():
            if (
                query_lower in device["label"].lower()
                or query_lower in vendor["label"].lower()
                or query_lower in model_key
            ):
                results.append(
                    {
                        "vendor_key": vendor_key,
                        "model_key": model_key,
                        "vendor_label": vendor["label"],
                        "device_label": device["label"],
                        "icon": vendor.get("icon"),
                        "u_height": device.get("u_height", 1),
                        "role": device.get("role"),
                        "telemetry_profile": device.get("telemetry_profile"),
                    }
                )

    results.append(
        {
            "vendor_key": None,
            "model_key": None,
            "vendor_label": None,
            "device_label": query,
            "icon": None,
            "u_height": 1,
            "role": None,
            "telemetry_profile": None,
            "_freeform": True,
        }
    )

    return results
