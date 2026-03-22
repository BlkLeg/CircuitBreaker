from datetime import UTC, datetime, timedelta

from app.db.models import (
    CapacityForecast,
    FlapIncident,
    HardwareLiveMetric,
    ResourceEfficiencyRecommendation,
)
from app.services.intelligence.analytics import (
    run_capacity_forecast,
    run_flap_detection,
    run_right_sizing,
)


def _seed_metrics(db, hw_id, days, start_pct, end_pct, metric="disk"):
    now = datetime.now(tz=UTC)
    delta = (end_pct - start_pct) / max(days - 1, 1)
    rows = [
        HardwareLiveMetric(
            hardware_id=hw_id,
            collected_at=now - timedelta(days=days - i),
            disk_pct=start_pct + i * delta if metric == "disk" else 30.0,
            cpu_pct=start_pct + i * delta if metric == "cpu" else 10.0,
            mem_pct=20.0,
            source="test",
            status="up",
        )
        for i in range(days)
    ]
    db.bulk_save_objects(rows)
    db.flush()


def test_capacity_forecast_growing_disk(db_session, factories):
    """14 days of ~1%/day growth from 43→57%: projected ~43 days to full."""
    hw = factories.hardware(name="storage-node", ip_address="10.5.5.1")
    _seed_metrics(db_session, hw.id, days=14, start_pct=43.0, end_pct=57.0)

    run_capacity_forecast(db_session)

    fc = db_session.query(CapacityForecast).filter_by(hardware_id=hw.id, metric="disk_pct").one()
    assert fc.slope_per_day > 0.8
    assert fc.projected_full_at is not None
    days_left = (fc.projected_full_at - datetime.now(tz=UTC)).days
    assert 30 < days_left < 60


def test_capacity_forecast_within_warning_threshold(db_session, factories):
    """93% now growing ~2%/day → days_left < warning_threshold_days=7."""
    hw = factories.hardware(name="full-soon", ip_address="10.5.5.2")
    _seed_metrics(db_session, hw.id, days=14, start_pct=65.0, end_pct=93.0)

    run_capacity_forecast(db_session, warning_days=7)

    fc = db_session.query(CapacityForecast).filter_by(hardware_id=hw.id, metric="disk_pct").one()
    assert fc.projected_full_at is not None
    days_left = (fc.projected_full_at - datetime.now(tz=UTC)).days
    assert days_left < 7


def test_right_sizing_under_provisioned(db_session, factories):
    """CPU avg 87% → under_provisioned."""
    hw = factories.hardware(name="pegged-node", ip_address="10.5.5.3")
    now = datetime.now(tz=UTC)
    db_session.bulk_save_objects(
        [
            HardwareLiveMetric(
                hardware_id=hw.id,
                collected_at=now - timedelta(days=30 - i),
                cpu_pct=85.0 + (i % 5),
                mem_pct=60.0,
                disk_pct=40.0,
                source="test",
                status="up",
            )
            for i in range(30)
        ]
    )
    db_session.flush()

    run_right_sizing(db_session)

    rec = (
        db_session.query(ResourceEfficiencyRecommendation)
        .filter_by(asset_type="hardware", asset_id=hw.id)
        .one()
    )
    assert rec.classification == "under_provisioned"
    assert rec.cpu_avg_pct > 80


def test_right_sizing_over_provisioned(db_session, factories):
    """CPU avg 2%, mem avg 5% → over_provisioned."""
    hw = factories.hardware(name="idle-node", ip_address="10.5.5.4")
    now = datetime.now(tz=UTC)
    db_session.bulk_save_objects(
        [
            HardwareLiveMetric(
                hardware_id=hw.id,
                collected_at=now - timedelta(days=30 - i),
                cpu_pct=2.0,
                mem_pct=5.0,
                disk_pct=10.0,
                source="test",
                status="up",
            )
            for i in range(30)
        ]
    )
    db_session.flush()

    run_right_sizing(db_session)

    rec = (
        db_session.query(ResourceEfficiencyRecommendation)
        .filter_by(asset_type="hardware", asset_id=hw.id)
        .one()
    )
    assert rec.classification == "over_provisioned"


def test_flap_detection_flags_flapping(db_session, factories):
    """6 status transitions in 30min → FlapIncident created."""
    hw = factories.hardware(name="flapper", ip_address="10.5.5.5")
    now = datetime.now(tz=UTC)
    statuses = ["up", "down", "up", "down", "up", "down", "up"]
    db_session.bulk_save_objects(
        [
            HardwareLiveMetric(
                hardware_id=hw.id,
                collected_at=now - timedelta(minutes=30 - i * 4),
                cpu_pct=10.0,
                mem_pct=20.0,
                disk_pct=30.0,
                source="test",
                status=s,
            )
            for i, s in enumerate(statuses)
        ]
    )
    db_session.flush()

    run_flap_detection(db_session)

    incident = (
        db_session.query(FlapIncident)
        .filter_by(asset_type="hardware", asset_id=hw.id)
        .one_or_none()
    )
    assert incident is not None
    assert incident.transition_count >= 5
    assert incident.is_active is True


def test_flap_detection_no_false_positive(db_session, factories):
    """Stable UP for 30min → no FlapIncident."""
    hw = factories.hardware(name="stable", ip_address="10.5.5.6")
    now = datetime.now(tz=UTC)
    db_session.bulk_save_objects(
        [
            HardwareLiveMetric(
                hardware_id=hw.id,
                collected_at=now - timedelta(minutes=28 - i * 2),
                cpu_pct=10.0,
                mem_pct=20.0,
                disk_pct=30.0,
                source="test",
                status="up",
            )
            for i in range(14)
        ]
    )
    db_session.flush()

    run_flap_detection(db_session)

    assert (
        db_session.query(FlapIncident).filter_by(asset_type="hardware", asset_id=hw.id).count() == 0
    )
