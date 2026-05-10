import uuid
from decimal import Decimal

from market_simulator.db.session import SessionLocal
from market_simulator.db.models.user import Plan


KNOWN_PLAN_SPECS = (
    {
        "code": "FREE",
        "name": "Free",
        "monthly_price_usd": Decimal("0.00"),
        "daily_free_runs": 5,
        "max_saved_strategies": 5,
        "max_tracked_strategies": 0,
        "builder_prompt_daily_limit": 20,
        "builder_prompt_max_chars": 1000,
        "max_backtest_years": 5,
        "max_comparison_runs": 4,
        "allow_portfolio_runs": False,
        "allow_comparison_runs": False,
        "allow_parameter_sweeps": False,
        "allow_ai_builder": True,
        "allow_strategy_history": False,
        "allow_rotation_templates": True,
        "allow_custom_rotation": False,
        "allow_rotation_edit": False,
        "allow_advanced_builder": False,
        "is_active": True,
    },
    {
        "code": "PRO",
        "name": "Pro",
        "monthly_price_usd": Decimal("19.99"),
        "daily_free_runs": 50,
        "max_saved_strategies": 50,
        "max_tracked_strategies": 10,
        "builder_prompt_daily_limit": 200,
        "builder_prompt_max_chars": 3000,
        "max_backtest_years": 15,
        "max_comparison_runs": 4,
        "allow_portfolio_runs": True,
        "allow_comparison_runs": True,
        "allow_parameter_sweeps": False,
        "allow_ai_builder": True,
        "allow_strategy_history": True,
        "allow_rotation_templates": True,
        "allow_custom_rotation": True,
        "allow_rotation_edit": True,
        "allow_advanced_builder": True,
        "is_active": True,
    },
    {
        "code": "BETA_TESTER",
        "name": "Beta Tester",
        "monthly_price_usd": Decimal("0.00"),
        "daily_free_runs": 999999,
        "max_saved_strategies": 999999,
        "max_tracked_strategies": 999999,
        "builder_prompt_daily_limit": 999999,
        "builder_prompt_max_chars": 20000,
        "max_backtest_years": 25,
        "max_comparison_runs": 4,
        "allow_portfolio_runs": True,
        "allow_comparison_runs": True,
        "allow_parameter_sweeps": True,
        "allow_ai_builder": True,
        "allow_strategy_history": True,
        "allow_rotation_templates": True,
        "allow_custom_rotation": True,
        "allow_rotation_edit": True,
        "allow_advanced_builder": True,
        "is_active": True,
    },
)


def seed():
    db = SessionLocal()
    try:
        existing_codes = {code for (code,) in db.query(Plan.code).all()}
        missing_specs = [
            plan_spec for plan_spec in KNOWN_PLAN_SPECS if plan_spec["code"] not in existing_codes
        ]

        if not missing_specs:
            print("All known plans already exist. Skipping.")
            return

        plans = [
            Plan(id=uuid.uuid4(), **plan_spec)
            for plan_spec in missing_specs
        ]

        db.add_all(plans)
        db.commit()

        inserted_codes = ", ".join(plan.code for plan in plans)
        print(f"Seeded missing plans: {inserted_codes}.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
