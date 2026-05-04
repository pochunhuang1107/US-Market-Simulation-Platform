from __future__ import annotations

import argparse
import sys

from market_simulator.db.session import SessionLocal
from market_simulator.services.user_provisioning import (
    ProvisioningError,
    format_provisioning_result,
    provision_user,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Provision a beta app user and plan subscription.")
    parser.add_argument("--email", required=True, help="OIDC/app email address to provision.")
    parser.add_argument("--display-name", help="Optional display name to set or update.")
    parser.add_argument(
        "--status",
        choices=["ACTIVE", "SUSPENDED", "DELETED"],
        help="User status to apply. Defaults to ACTIVE for newly created users.",
    )
    parser.add_argument("--plan-code", default="FREE", help="Plan code to assign if missing.")
    parser.add_argument("--user-id", help="Optional UUID to use when creating the user.")
    parser.add_argument("--provider", help="Optional provider label for newly assigned subscriptions.")
    parser.add_argument("--external-provider", help="Optional external identity provider to link.")
    parser.add_argument("--external-subject", help="Optional external identity subject to link.")
    parser.add_argument("--dry-run", action="store_true", help="Report changes without committing them.")
    parser.add_argument(
        "--deactivate",
        action="store_true",
        help="Set an existing or newly created user to SUSPENDED.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.deactivate and args.status and args.status != "SUSPENDED":
        parser.error("--deactivate cannot be combined with --status other than SUSPENDED")

    status = "SUSPENDED" if args.deactivate else args.status or "ACTIVE"
    update_status = args.deactivate or args.status is not None

    db = SessionLocal()
    try:
        result = provision_user(
            db,
            email=args.email,
            display_name=args.display_name,
            update_display_name=args.display_name is not None,
            status=status,
            update_status=update_status,
            plan_code=args.plan_code,
            user_id=args.user_id,
            provider=args.provider,
            external_provider=args.external_provider,
            external_subject=args.external_subject,
            dry_run=args.dry_run,
        )
    except ProvisioningError as exc:
        db.rollback()
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()

    print(format_provisioning_result(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
