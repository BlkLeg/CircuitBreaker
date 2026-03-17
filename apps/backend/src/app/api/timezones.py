import functools
from zoneinfo import available_timezones

from fastapi import APIRouter

router = APIRouter(tags=["timezones"])


@functools.lru_cache(maxsize=1)
def _sorted_timezones() -> list[str]:
    return sorted(available_timezones())


@router.get("")
def get_timezones() -> dict[str, list[str]]:
    """Return a sorted list of all valid IANA timezone strings. No auth required."""
    return {"timezones": _sorted_timezones()}
