from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.cve_models import CVECacheBase, CVEFeedGeneration
from app.db.models import Hardware
from app.schemas.cve import AssessmentIdentity, FeedState, IdentityPatch
from app.services.intelligence.cve_assessment import (
    assess_entity,
    assess_identity,
    evaluate_candidates,
    get_feed_state,
    readiness_result,
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


def test_an_uncorrected_identity_reports_the_revision_a_correction_must_send(db_session):
    """The revision is the override row's token, and no override yet means 0.

    Reporting 1 for an inventory identity made the very first correction from
    the UI conflict with itself: the client echoed the identity's revision back
    and the server compared it against the absent row's 0.
    """
    db = db_session
    hardware = Hardware(name="uncorrected-host")
    db.add(hardware)
    db.commit()

    identity = resolve_assessment_identity(db, "hardware", hardware.id)

    assert identity.provenance == "inventory"
    assert identity.revision == 0

    created = update_assessment_identity(
        db,
        "hardware",
        hardware.id,
        IdentityPatch(product="widget", version="1.10", revision=identity.revision),
        actor="7",
    )
    db.commit()

    assert created.revision == 1
    assert resolve_assessment_identity(db, "hardware", hardware.id).revision == 1


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


def _ready_feed():
    return FeedState(
        state="ready",
        reason_code="ready",
        generation="gen-1",
        completed_at=datetime.now(UTC),
        age_seconds=60,
        total_records=1,
        coverage_complete=True,
    )


def _identity(**over):
    base = {
        "vendor": "acme",
        "product": "widget",
        "version": "1.9",
        "version_scheme": "dotted_numeric",
        "provenance": "inventory",
        "revision": 0,
    }
    base.update(over)
    return AssessmentIdentity(**base)


def test_readiness_returns_none_when_matching_must_run():
    assert readiness_result(_identity(), _ready_feed(), datetime.now(UTC)) is None


def test_readiness_decides_a_missing_product_without_touching_the_cache():
    result = readiness_result(_identity(product=None), _ready_feed(), datetime.now(UTC))

    assert result is not None
    assert result.state == "unassessed"
    assert result.reason_code == "identity_missing"


def test_evaluate_candidates_reports_a_caller_supplied_candidate_limit():
    result = evaluate_candidates(
        [], _identity(), _ready_feed(), datetime.now(UTC), candidate_limited=True
    )

    assert result.state == "partial"
    assert result.reason_code == "candidate_limit"
    assert "Candidate limit reached; coverage is partial." in result.limitations


def test_assess_identity_matches_the_same_finding_assess_entity_does(db_session):
    db = db_session
    hardware = Hardware(name="host", vendor="acme", model="widget", os_version="1.9")
    db.add(hardware)
    db.commit()
    cache = _cache_session()
    generation = start_feed_generation(cache)
    ingest_feed_page(cache, generation, [_nvd_record()])
    complete_feed_generation(cache, generation, total_records=1)
    cache.commit()

    entity_result = assess_entity(db, cache, "hardware", hardware.id)
    identity = resolve_assessment_identity(db, "hardware", hardware.id)
    feed = get_feed_state(cache, None, entity_result.assessed_at)
    identity_result = assess_identity(cache, identity, feed, entity_result.assessed_at)

    assert entity_result.state == identity_result.state
    assert [f.cve_id for f in entity_result.findings] == [
        f.cve_id for f in identity_result.findings
    ]
