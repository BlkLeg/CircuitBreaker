from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.cve_models import CVECacheBase
from app.db.models import ComputeUnit, Hardware, Service
from app.schemas.cve import IdentityPatch
from app.services.intelligence.cve_assessment import update_assessment_identity
from app.services.intelligence.fleet_assessment import (
    group_by_identity,
    resolve_fleet_identities,
)


def _cache_session():
    engine = create_engine("sqlite:///:memory:")
    CVECacheBase.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_resolves_all_three_assessable_entity_types(db_session):
    db = db_session
    host = Hardware(name="pve-01")
    db.add(host)
    db.commit()
    db.add_all(
        [
            Hardware(name="nas-01", vendor="acme", model="widget", os_version="1.9"),
            ComputeUnit(name="vm-jellyfin", kind="vm", hardware_id=host.id, os="debian"),
            Service(name="nginx", slug="nginx"),
        ]
    )
    db.commit()

    entities = resolve_fleet_identities(db)

    by_type = {e.entity_type for e in entities}
    assert by_type == {"hardware", "compute_unit", "service"}
    assert {e.name for e in entities} >= {"nas-01", "vm-jellyfin", "nginx"}


def test_identical_hosts_collapse_to_one_identity_key(db_session):
    db = db_session
    db.add_all(
        [
            Hardware(name=f"node-{i}", vendor="acme", model="widget", os_version="1.9")
            for i in range(5)
        ]
    )
    db.commit()

    groups = group_by_identity(resolve_fleet_identities(db))
    matching = [items for key, items in groups.items() if key[1] == "widget"]

    assert len(matching) == 1
    assert len(matching[0]) == 5


def test_an_operator_correction_moves_an_entity_to_its_own_key(db_session):
    db = db_session
    first = Hardware(name="a", vendor="acme", model="widget", os_version="1.9")
    second = Hardware(name="b", vendor="acme", model="widget", os_version="1.9")
    db.add_all([first, second])
    db.commit()
    update_assessment_identity(
        db,
        "hardware",
        second.id,
        IdentityPatch(vendor="acme", product="widget", version="2.0", revision=0),
        actor="test",
    )
    db.commit()

    groups = group_by_identity(resolve_fleet_identities(db))
    widget_keys = {key for key in groups if key[1] == "widget"}

    assert len(widget_keys) == 2


def test_identity_key_folds_case_so_vendor_spelling_does_not_split_a_group(db_session):
    db = db_session
    db.add_all(
        [
            Hardware(name="a", vendor="ACME", model="Widget", os_version="1.9"),
            Hardware(name="b", vendor="acme", model="widget", os_version="1.9"),
        ]
    )
    db.commit()

    groups = group_by_identity(resolve_fleet_identities(db))

    assert len([key for key in groups if key[1] == "widget"]) == 1
