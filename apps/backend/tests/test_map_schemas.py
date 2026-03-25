"""Unit tests for multi-map Pydantic schemas (no DB required)."""

import pytest
from pydantic import ValidationError

from app.schemas.map import MapCreate, MapOut, MapUpdate


def test_map_create_valid():
    m = MapCreate(name="DMZ")
    assert m.name == "DMZ"


def test_map_create_empty_name_rejected():
    with pytest.raises(ValidationError):
        MapCreate(name="")


def test_map_create_long_name_rejected():
    with pytest.raises(ValidationError):
        MapCreate(name="x" * 65)


def test_map_update_partial():
    m = MapUpdate(sort_order=2)
    assert m.name is None
    assert m.sort_order == 2


def test_map_out_from_orm():
    class FakeOrm:
        id = 1
        name = "Main"
        is_default = True
        sort_order = 0
        entity_count = 5

    out = MapOut.model_validate(FakeOrm())
    assert out.name == "Main"
    assert out.entity_count == 5
