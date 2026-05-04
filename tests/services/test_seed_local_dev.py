from __future__ import annotations

import sys
from pathlib import Path

from market_simulator.db.models.user import Plan, User, UserPlanSubscription

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import seed_local_dev  # noqa: E402
import seed_plans  # noqa: E402
import seed_user  # noqa: E402


def test_seed_local_dev_creates_plans_and_default_user(db_session, monkeypatch):
    monkeypatch.setattr(seed_plans, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(seed_user, "SessionLocal", lambda: db_session)

    seed_local_dev.seed()

    plan_codes = {plan.code for plan in db_session.query(Plan).all()}
    user = db_session.query(User).filter(User.email == "test@example.com").one()
    subscription = db_session.query(UserPlanSubscription).one()

    assert plan_codes == {"FREE", "PRO"}
    assert str(user.id) == seed_user.USER_ID
    assert subscription.user_id == user.id


def test_seed_local_dev_is_idempotent(db_session, monkeypatch):
    monkeypatch.setattr(seed_plans, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(seed_user, "SessionLocal", lambda: db_session)

    seed_local_dev.seed()
    seed_local_dev.seed()

    assert db_session.query(Plan).count() == 2
    assert db_session.query(User).count() == 1
    assert db_session.query(UserPlanSubscription).count() == 1
