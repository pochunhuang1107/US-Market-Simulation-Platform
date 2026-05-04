from market_simulator.db.session import SessionLocal
from market_simulator.services.user_provisioning import format_provisioning_result, provision_user


USER_ID = "00000000-0000-0000-0000-000000000001"


def seed():
    db = SessionLocal()
    try:
        result = provision_user(
            db,
            email="test@example.com",
            display_name="Test User",
            update_display_name=False,
            status="ACTIVE",
            update_status=False,
            plan_code="FREE",
            user_id=USER_ID,
        )
    finally:
        db.close()

    print(format_provisioning_result(result))


if __name__ == "__main__":
    seed()
