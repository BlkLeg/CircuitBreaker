from datetime import UTC, datetime

from app.db.models import TelemetryTimeseries
from app.services.monitoring.collectors import Sample
from app.services.monitoring.writer import write_samples


def test_write_samples_bulk_inserts_rows(db_session):
    ts = datetime.now(UTC)
    rows = [
        (7, "hardware", 3, [Sample("avail", 1.0), Sample("packet_loss_pct", 0.0)], ts),
        (8, "ip", None, [Sample("avail", 0.0, error_reason="icmp_unavailable")], ts),
    ]
    n = write_samples(db_session, rows)
    db_session.commit()
    assert n == 3

    stored = db_session.query(TelemetryTimeseries).filter(TelemetryTimeseries.item_id == 7).all()
    metrics = {r.metric: r.value for r in stored}
    assert metrics == {"avail": 1.0, "packet_loss_pct": 0.0}
    assert all(r.source == "monitor" for r in stored)
