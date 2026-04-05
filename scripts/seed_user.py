import uuid

from market_simulator.db.session import SessionLocal
from market_simulator.db.models.user import User, UserPlanSubscription, Plan


USER_ID = "00000000-0000-0000-0000-000000000001"


def seed():
    db = SessionLocal()

    existing = db.query(User).filter(User.id == USER_ID).first()
    if existing:
        print("User already exists")
        return

    # create user
    user = User(
        id=USER_ID,
        email="test@example.com",
        display_name="Test User",
        status="ACTIVE",
    )

    db.add(user)
    db.commit()

    # assign FREE plan
    free_plan = db.query(Plan).filter(Plan.code == "FREE").first()

    sub = UserPlanSubscription(
        user_id=user.id,
        plan_id=free_plan.id,
        status="ACTIVE",
        starts_at="2024-01-01",
        auto_renew=False,
    )

    db.add(sub)
    db.commit()

    print("Seeded user successfully")


if __name__ == "__main__":
    seed()