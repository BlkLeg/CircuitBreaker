"""Dev-only: flip the instance back into the OOBE wizard's first-run state.

Sets ``auth_enabled`` back to false (the sole gate ``bootstrap_status`` checks)
and rewinds the onboarding step, so the next page load shows the wizard from
the start. Existing users are left in place; ``bootstrap_initialize`` wipes
any stale users itself once you complete the wizard again.
"""

from __future__ import annotations

from app.db.models import Onboarding
from app.db.session import SessionLocal
from app.services.settings_service import get_or_create_settings


def main() -> int:
    db = SessionLocal()
    try:
        cfg = get_or_create_settings(db)
        cfg.auth_enabled = False

        row = db.get(Onboarding, 1)
        if row:
            row.step = "start"
            row.previous_step = "start"
        else:
            db.add(Onboarding(id=1, step="start", previous_step="start"))

        db.commit()
    finally:
        db.close()

    print("OOBE reset: next page load will show the first-run wizard.")
    print("Existing users are untouched until you complete the wizard again.")
    print(
        "Use a private/incognito window (or clear the localhost session cookie) "
        "so the browser doesn't skip straight past it."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
