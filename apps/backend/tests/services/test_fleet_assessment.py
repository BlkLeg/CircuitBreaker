import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.db.cve_models import CVECacheBase
from app.db.models import ComputeUnit, Hardware, Service
from app.schemas.cve import AssessmentIdentity, IdentityPatch
from app.services.intelligence.cve_assessment import (
    assess_entity,
    update_assessment_identity,
)
from app.services.intelligence.cve_feed import (
    complete_feed_generation,
    ingest_feed_page,
    start_feed_generation,
)
from app.services.intelligence.fleet_assessment import (
    assess_fleet,
    candidates_for,
    group_by_identity,
    resolve_fleet_identities,
    select_candidates,
)
from app.services.intelligence.fleet_cache import clear_identity_cache


@pytest.fixture(autouse=True)
def _clean_identity_cache():
    """A memo that survived between tests would make them pass in isolation only."""
    clear_identity_cache()
    yield
    clear_identity_cache()


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


def _record(cve_id, vendor, product, *, score=8.1):
    return {
        "cve": {
            "id": cve_id,
            "descriptions": [{"lang": "en", "value": "Example issue"}],
            "metrics": {
                "cvssMetricV31": [{"cvssData": {"baseScore": score, "baseSeverity": "HIGH"}}]
            },
            "published": "2026-09-01T00:00:00Z",
            "configurations": [
                {
                    "nodes": [
                        {
                            "operator": "OR",
                            "cpeMatch": [
                                {
                                    "criteria": f"cpe:2.3:a:{vendor}:{product}:*:*:*:*:*:*:*:*",
                                    "vulnerable": True,
                                    "versionStartIncluding": "1.0",
                                    "versionEndExcluding": "9.0",
                                }
                            ],
                        }
                    ]
                }
            ],
        }
    }


def _seeded_cache(records):
    cache = _cache_session()
    generation = start_feed_generation(cache)
    ingest_feed_page(cache, generation, records)
    complete_feed_generation(cache, generation, total_records=len(records))
    cache.commit()
    return cache, generation.id


class _QueryCounter:
    """Counts statements touching cve_applicability on one engine."""

    def __init__(self, session):
        self.count = 0
        self._engine = session.get_bind()
        event.listen(self._engine, "before_cursor_execute", self._on_execute)

    def _on_execute(self, conn, cursor, statement, parameters, context, executemany):
        if "cve_applicability" in statement:
            self.count += 1

    def stop(self):
        event.remove(self._engine, "before_cursor_execute", self._on_execute)


def test_one_statement_covers_every_product_in_the_pass():
    cache, generation = _seeded_cache(
        [
            _record("CVE-2026-0001", "acme", "widget"),
            _record("CVE-2026-0002", "globex", "gadget"),
            _record("CVE-2026-0003", "initech", "sprocket"),
        ]
    )
    counter = _QueryCounter(cache)
    try:
        pool = select_candidates(cache, generation, {"widget", "gadget", "sprocket"})
    finally:
        counter.stop()

    assert counter.count == 1
    assert set(pool.by_pair) == {("acme", "widget"), ("globex", "gadget"), ("initech", "sprocket")}


def test_an_identity_with_a_vendor_takes_only_its_own_pair():
    cache, generation = _seeded_cache(
        [
            _record("CVE-2026-0001", "acme", "widget"),
            _record("CVE-2026-0002", "other", "widget"),
        ]
    )
    pool = select_candidates(cache, generation, {"widget"})
    identity = AssessmentIdentity(
        vendor="acme",
        product="widget",
        version="1.9",
        version_scheme="dotted_numeric",
        provenance="inventory",
        revision=0,
    )

    records, limited = candidates_for(pool, identity)

    assert [r.cve_id for r in records] == ["CVE-2026-0001"]
    assert limited is False


def test_an_identity_with_no_vendor_takes_every_vendor_for_its_product():
    cache, generation = _seeded_cache(
        [
            _record("CVE-2026-0001", "acme", "widget"),
            _record("CVE-2026-0002", "other", "widget"),
        ]
    )
    pool = select_candidates(cache, generation, {"widget"})
    identity = AssessmentIdentity(
        vendor=None,
        product="widget",
        version="1.9",
        version_scheme="dotted_numeric",
        provenance="inventory",
        revision=0,
    )

    records, limited = candidates_for(pool, identity)

    assert {r.cve_id for r in records} == {"CVE-2026-0001", "CVE-2026-0002"}
    assert limited is False


def test_a_noisy_product_does_not_starve_another_products_budget(monkeypatch):
    monkeypatch.setattr("app.services.intelligence.fleet_assessment.MAX_CANDIDATES", 2)
    cache, generation = _seeded_cache(
        [_record(f"CVE-2026-10{i:02d}", "acme", "widget") for i in range(5)]
        + [_record("CVE-2026-2001", "globex", "gadget")]
    )

    pool = select_candidates(cache, generation, {"widget", "gadget"})

    assert len(pool.by_pair[("acme", "widget")]) == 2
    assert ("acme", "widget") in pool.capped_pairs
    assert len(pool.by_pair[("globex", "gadget")]) == 1
    assert ("globex", "gadget") not in pool.capped_pairs


def test_fleet_row_agrees_with_the_entity_panel_for_the_same_entity(db_session):
    db = db_session
    hardware = Hardware(name="nas-01", vendor="acme", model="widget", os_version="1.9")
    db.add(hardware)
    db.commit()
    cache, _ = _seeded_cache([_record("CVE-2026-0001", "acme", "widget")])

    fleet = assess_fleet(db, cache)
    row = next(r for r in fleet.rows if r.entity_type == "hardware" and r.entity_id == hardware.id)
    entity = assess_entity(db, cache, "hardware", hardware.id)

    assert row.state == entity.state
    assert row.reason_code == entity.reason_code
    assert row.finding_count == entity.total


def test_an_entity_with_no_product_is_unassessed_not_clean(db_session):
    db = db_session
    hardware = Hardware(name="mystery-box")
    db.add(hardware)
    db.commit()
    cache, _ = _seeded_cache([_record("CVE-2026-0001", "acme", "widget")])

    fleet = assess_fleet(db, cache)
    row = next(r for r in fleet.rows if r.entity_id == hardware.id and r.entity_type == "hardware")

    assert row.state == "unassessed"
    assert row.reason_code == "identity_missing"
    assert row.finding_count == 0
    assert fleet.summary.by_state["unassessed"] >= 1


def test_no_ingested_feed_makes_every_row_unavailable(db_session):
    db = db_session
    db.add(Hardware(name="nas-01", vendor="acme", model="widget", os_version="1.9"))
    db.commit()
    cache = _cache_session()

    fleet = assess_fleet(db, cache)

    assert fleet.feed.state == "unavailable"
    assert fleet.rows
    assert {row.state for row in fleet.rows} == {"unavailable"}
    assert fleet.summary.entities_with_findings == 0


def test_summary_counts_reconcile_with_the_rows(db_session):
    db = db_session
    db.add_all(
        [
            Hardware(name="a", vendor="acme", model="widget", os_version="1.9"),
            Hardware(name="b", vendor="acme", model="widget", os_version="1.9"),
            Hardware(name="c"),
        ]
    )
    db.commit()
    cache, _ = _seeded_cache([_record("CVE-2026-0001", "acme", "widget")])

    fleet = assess_fleet(db, cache)

    assert fleet.summary.total_entities == len(fleet.rows)
    assert sum(fleet.summary.by_state.values()) == len(fleet.rows)
    assert fleet.summary.entities_with_findings == sum(
        1 for row in fleet.rows if row.finding_count > 0
    )
    assert fleet.summary.findings_total == sum(row.finding_count for row in fleet.rows)


def test_identical_hosts_are_assessed_once_and_reported_twice(db_session, monkeypatch):
    db = db_session
    db.add_all(
        [
            Hardware(name=f"node-{i}", vendor="acme", model="widget", os_version="1.9")
            for i in range(6)
        ]
    )
    db.commit()
    cache, _ = _seeded_cache([_record("CVE-2026-0001", "acme", "widget")])

    calls = {"n": 0}
    import app.services.intelligence.fleet_assessment as module

    original = module.evaluate_candidates

    def counting(*args, **kwargs):
        calls["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "evaluate_candidates", counting)

    fleet = assess_fleet(db, cache)

    assert calls["n"] == 1
    assert len([r for r in fleet.rows if r.finding_count > 0]) == 6


def test_the_identity_cap_marks_the_remainder_instead_of_dropping_it(db_session):
    db = db_session
    db.add_all(
        [
            Hardware(name=f"n{i}", vendor="acme", model=f"widget{i}", os_version="1.9")
            for i in range(4)
        ]
    )
    db.commit()
    cache, _ = _seeded_cache([_record("CVE-2026-0001", "acme", "widget0")])

    fleet = assess_fleet(db, cache, identity_limit=2)

    assert len(fleet.rows) == 4
    assert fleet.limits.identity_limit_reached is True
    assert fleet.limits.identities_assessed == 2
    assert any(row.reason_code == "fleet_limit" for row in fleet.rows)
    assert all(row.state == "unassessed" for row in fleet.rows if row.reason_code == "fleet_limit")
