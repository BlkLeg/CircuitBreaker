from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.db.cve_models import CVECacheBase
from app.db.models import ComputeUnit, Hardware, Service
from app.schemas.cve import AssessmentIdentity, IdentityPatch
from app.services.intelligence.cve_assessment import update_assessment_identity
from app.services.intelligence.cve_feed import (
    complete_feed_generation,
    ingest_feed_page,
    start_feed_generation,
)
from app.services.intelligence.fleet_assessment import (
    candidates_for,
    group_by_identity,
    resolve_fleet_identities,
    select_candidates,
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
