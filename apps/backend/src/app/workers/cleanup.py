from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings


def cleanup_old_icons(db: Session) -> int:
    """Delete user icons that have not been referenced for 30 days.

    This is a lightweight placeholder worker function intended for APScheduler wiring.
    Returns the number of files removed.
    """
    cutoff = datetime.now(UTC) - timedelta(days=30)
    rows = db.execute(
        text(
            """
            SELECT id, filename
            FROM user_icons
            WHERE uploaded_at IS NOT NULL
              AND uploaded_at < :cutoff
            """
        ),
        {"cutoff": cutoff.isoformat()},
    ).fetchall()

    icons_dir = Path(settings.uploads_dir) / "icons"
    removed = 0

    for icon_id, filename in rows:
        if filename:
            (icons_dir / filename).unlink(missing_ok=True)
        db.execute(text("DELETE FROM user_icons WHERE id = :id"), {"id": icon_id})
        removed += 1

    if removed:
        db.commit()
    return removed
