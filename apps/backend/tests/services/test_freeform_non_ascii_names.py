"""Freeform first, on the clusters users actually have (QUAR-001 / #162).

CLAUDE.md: any `name`/`model`/`vendor` the user types must save. Every mono
cluster initialised before the UTF8 `initdb` fix is SQL_ASCII, and a psycopg2
connection that does not ask for an encoding there gets Python's `ascii` codec —
so "Büro", an em dash or a Japanese rack label raised UnicodeEncodeError on
save. `sql_ascii_session` is the production engine pointed at such a database.
"""

from __future__ import annotations

from sqlalchemy import select

from app.db.models import Hardware
from app.schemas.hardware import HardwareCreate
from app.services import hardware_service

_NAME = "Büro-Server — ラック 日本"
_LOCATION = "Salle serveur é — 東京"
_MODEL = "Modèle — 日本"
_NOTES = "naïve café, 冷却 OK — ✓"


def test_a_non_ascii_device_round_trips_on_a_sql_ascii_cluster(sql_ascii_session):
    created = hardware_service.create_hardware(
        sql_ascii_session,
        HardwareCreate(name=_NAME, location=_LOCATION, model=_MODEL, notes=_NOTES),
    )

    sql_ascii_session.expire_all()
    row = sql_ascii_session.execute(
        select(Hardware).where(Hardware.id == created["id"])
    ).scalar_one()
    assert (row.name, row.location, row.model, row.notes) == (_NAME, _LOCATION, _MODEL, _NOTES)


def test_a_non_ascii_name_is_findable_by_equality_on_a_sql_ascii_cluster(sql_ascii_session):
    """The bytes stored are the UTF-8 encoding, not a lossy substitute: a lookup
    by the same string matches, which a `?`-replaced value would not."""
    created = hardware_service.create_hardware(sql_ascii_session, HardwareCreate(name=_NAME))

    found = sql_ascii_session.execute(
        select(Hardware.id).where(Hardware.name == _NAME)
    ).scalar_one()
    assert found == created["id"]
