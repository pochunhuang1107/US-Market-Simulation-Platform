from __future__ import annotations

import sys

from sqlalchemy.exc import OperationalError, SQLAlchemyError

from market_simulator.services.user_provisioning import ProvisioningError
import seed_plans
import seed_user


def seed() -> None:
    """Initialize data needed by the local compose dev stack."""
    seed_plans.seed()
    seed_user.seed()


def main() -> int:
    try:
        seed()
    except OperationalError as exc:
        print(
            "error: database is unavailable; confirm Postgres is running and DATABASE_URL is correct",
            file=sys.stderr,
        )
        print(f"details: {exc}", file=sys.stderr)
        return 1
    except (ProvisioningError, SQLAlchemyError) as exc:
        print(f"error: local dev seed failed: {exc}", file=sys.stderr)
        return 1

    print("Local dev seed data is ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
