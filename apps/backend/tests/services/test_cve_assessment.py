from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.cve_models import CVECacheBase, CVEFeedGeneration
from app.db.models import Hardware
from app.schemas.cve import IdentityPatch
from app.services.intelligence.cve_assessment import (
    assess_entity,
    resolve_assessment_identity,
    update_assessment_identity,
)
from app.services.intelligence.cve_feed import (
    complete_feed_generation,
    ingest_feed_page,
    start_feed_generation,
)


def _cache_session():
    engine = create_engine("sqlite:///:memory:")
    CVECacheBase.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _nvd_record(*, end_excluding="1.10"):
    return {
        "cve": {
            "id": "CVE-2026-0001",
            "descriptions": [{"lang": "en", "value": "Example issue"}],
            "metrics": {
                "cvssMetricV31": [{"cvssData": {"baseScore": 8.1, "baseSeverity": "HIGH"}}]
            },
            "published": "2026-09-01T00:00:00Z",
            "configurations": [
                {
                    "nodes": [
                        {
                            "operator": "OR",
                            "cpeMatch": [
                                {
                                    "criteria": "cpe:2.3:a:acme:widget:*:*:*:*:*:*:*:*",
                                    "vulnerable": True,
                                    "versionStartIncluding": "1.0",
                                    "versionEndExcluding": end_excluding,
                                }
                            ],
                        }
                    ]
                }
            ],
        }
    }


def test_empty_or_incomplete_feed_cannot_produce_completed_assessment(db_session):
    db = db_session
    hardware = Hardware(name="host", vendor="acme", model="widget", os_version="1.9")
    db.add(hardware)
    db.commit()
    cache = _cache_session()
    generation = start_feed_generation(cache)
    complete_feed_generation(cache, generation, total_records=0)
    cache.commit()

    result = assess_entity(db, cache, "hardware", hardware.id)

    assert result.state == "unavailable"
    assert result.reason_code == "feed_incomplete"
    assert result.completeness == "none"


def test_completed_assessment_distinguishes_match_from_exclusive_boundary(db_session):
    db = db_session
    first = Hardware(name="old", vendor="acme", model="widget", os_version="1.9")
    second = Hardware(name="new", vendor="acme", model="widget", os_version="1.10")
    db.add_all([first, second])
    db.commit()
    cache = _cache_session()
    generation = start_feed_generation(cache)
    ingest_feed_page(cache, generation, [_nvd_record()])
    complete_feed_generation(cache, generation, total_records=1)
    cache.commit()

    matching = assess_entity(db, cache, "hardware", first.id)
    excluded = assess_entity(db, cache, "hardware", second.id)

    assert matching.state == "completed"
    assert [finding.cve_id for finding in matching.findings] == ["CVE-2026-0001"]
    assert excluded.state == "completed"
    assert excluded.findings == []


def test_stale_complete_feed_returns_stale_not_clean(db_session):
    db = db_session
    hardware = Hardware(name="host", vendor="acme", model="widget", os_version="1.10")
    db.add(hardware)
    db.commit()
    cache = _cache_session()
    generation = start_feed_generation(cache)
    ingest_feed_page(cache, generation, [_nvd_record()])
    complete_feed_generation(cache, generation, total_records=1)
    generation.completed_at = datetime.now(UTC) - timedelta(days=10)
    cache.commit()

    result = assess_entity(db, cache, "hardware", hardware.id)

    assert result.state == "stale"
    assert result.reason_code == "feed_stale"


def test_identity_updates_are_revision_checked(db_session):
    db = db_session
    hardware = Hardware(name="host")
    db.add(hardware)
    db.commit()

    created = update_assessment_identity(
        db,
        "hardware",
        hardware.id,
        IdentityPatch(
            vendor="acme",
            product="widget",
            version="1.10",
            version_scheme="dotted_numeric",
            revision=0,
        ),
        actor="7",
    )
    db.commit()

    assert created.revision == 1
    assert resolve_assessment_identity(db, "hardware", hardware.id).provenance == "operator"

    from app.core.errors import ConflictError

    try:
        update_assessment_identity(
            db,
            "hardware",
            hardware.id,
            IdentityPatch(product="other", revision=0),
            actor="7",
        )
    except ConflictError as exc:
        assert exc.error_code == "stale_identity"
    else:
        raise AssertionError("stale identity revision was accepted")


def test_failed_refresh_does_not_replace_previous_complete_generation():
    cache = _cache_session()
    complete = start_feed_generation(cache)
    ingest_feed_page(cache, complete, [_nvd_record()])
    complete_feed_generation(cache, complete, total_records=1)
    failed = CVEFeedGeneration(
        id="failed",
        source="nvd",
        status="failed",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        coverage_complete=False,
    )
    cache.add(failed)
    cache.commit()

    from app.services.intelligence.cve_feed import active_feed_generation

    assert active_feed_generation(cache).id == complete.id
