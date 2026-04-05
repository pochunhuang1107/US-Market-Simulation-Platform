import uuid
from datetime import datetime

from market_simulator.db.session import SessionLocal
from market_simulator.db.models.user import Plan


def seed():
    db = SessionLocal()

    existing = db.query(Plan).count()
    if existing > 0:
        print("Plans already exist. Skipping.")
        return

    plans = [
        Plan(
            id=uuid.uuid4(),
            code="FREE",
            name="Free",
            monthly_price_usd=0,
            daily_free_runs=5,
            max_saved_strategies=5,
            max_tracked_strategies=0,
            allow_portfolio_runs=False,
            allow_comparison_runs=False,
            allow_parameter_sweeps=False,
            allow_ai_builder=False,
            allow_strategy_history=False,
            is_active=True,
        ),
        Plan(
            id=uuid.uuid4(),
            code="PRO",
            name="Pro",
            monthly_price_usd=19.99,
            daily_free_runs=999999,
            max_saved_strategies=100,
            max_tracked_strategies=10,
            allow_portfolio_runs=True,
            allow_comparison_runs=True,
            allow_parameter_sweeps=False,
            allow_ai_builder=True,
            allow_strategy_history=True,
            is_active=True,
        ),
        Plan(
            id=uuid.uuid4(),
            code="POWER",
            name="Power",
            monthly_price_usd=49.99,
            daily_free_runs=999999,
            max_saved_strategies=1000,
            max_tracked_strategies=100,
            allow_portfolio_runs=True,
            allow_comparison_runs=True,
            allow_parameter_sweeps=True,
            allow_ai_builder=True,
            allow_strategy_history=True,
            is_active=True,
        ),
    ]

    db.add_all(plans)
    db.commit()

    print("Seeded plans successfully.")


if __name__ == "__main__":
    seed()