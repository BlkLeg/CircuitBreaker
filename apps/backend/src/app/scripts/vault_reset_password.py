"""Reset a local user's password by proving possession of the vault key."""

from __future__ import annotations

import argparse
import sys

from fastapi import HTTPException

from app.db.session import SessionLocal
from app.services.auth_service import vault_reset_password
from app.services.settings_service import get_or_create_settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reset a local user's password using the current Circuit Breaker vault key."
    )
    parser.add_argument("--email", required=True, help="Email address of the local user to reset.")
    parser.add_argument(
        "--vault-key",
        required=True,
        help="The backed-up CB_VAULT_KEY value shown during OOBE.",
    )
    parser.add_argument(
        "--new-password",
        required=True,
        help="Replacement password that satisfies the app password policy.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        cfg = get_or_create_settings(db)
        if not cfg.jwt_secret:
            print("Auth is not configured for this instance.", file=sys.stderr)
            return 1

        vault_reset_password(
            db,
            args.email,
            args.vault_key,
            args.new_password,
            cfg,
            auto_login=False,
        )
    except HTTPException as exc:
        print(str(exc.detail), file=sys.stderr)
        return 1
    finally:
        db.close()

    print(f"Password reset completed for {args.email}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
