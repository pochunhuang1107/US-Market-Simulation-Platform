from __future__ import annotations

import os
import uuid
from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from market_simulator.api.deps import get_current_user, get_db
from market_simulator.api.main import app
from market_simulator.db.base import Base
import market_simulator.db.models  # noqa: F401
from market_simulator.db.enums import StrategyType, UserStatus
from market_simulator.db.models.strategy import Strategy, StrategyVersion
from market_simulator.db.models.user import User


TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/market_simulator_test",
)

engine = create_engine(
    TEST_DATABASE_URL,
    pool_pre_ping=True,
    future=True,
)

TestingSessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    future=True,
)


@pytest.fixture(scope="session", autouse=True)
def create_test_schema() -> Generator[None, None, None]:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def clean_database() -> Generator[None, None, None]:
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(text(f'TRUNCATE TABLE "{table.name}" RESTART IDENTITY CASCADE'))
    yield


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def current_user_ctx() -> dict[str, str]:
    return {"id": "00000000-0000-0000-0000-000000000001"}


@pytest.fixture
def client(db_session: Session, current_user_ctx: dict[str, str]) -> Generator[TestClient, None, None]:
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    def override_get_current_user():
        return {"id": current_user_ctx["id"]}

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def _default_strategy_config() -> dict[str, Any]:
    return {
        "name": "test-strategy",
        "symbol": "QQQ",
        "benchmark": "QQQ",
        "start_date": "2019-01-02",
        "end_date": "2024-12-31",
        "initial_capital": 100000,
        "transaction_cost_bps": 5,
        "position_sizing": {
            "type": "percent_of_equity",
            "value": 1.0,
        },
        "entry": {
            "type": "rsi_below",
            "lookback": 14,
            "threshold": 30,
        },
        "exit": {
            "type": "rsi_above",
            "lookback": 14,
            "threshold": 70,
        },
        "risk": {
            "stop_loss_pct": None,
            "take_profit_pct": None,
        },
    }


@pytest.fixture
def create_user(db_session: Session):
    def _create_user(
        *,
        user_id: str | None = None,
        email: str | None = None,
        display_name: str = "Test User",
    ) -> User:
        user_uuid = uuid.UUID(user_id) if user_id else uuid.uuid4()
        user = User(
            id=user_uuid,
            email=email or f"{user_uuid}@example.com",
            password_hash=None,
            display_name=display_name,
            status=UserStatus.ACTIVE,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        return user

    return _create_user


@pytest.fixture
def create_strategy_bundle(db_session: Session):
    def _create_strategy_bundle(
        *,
        user_id: str,
        strategy_name: str = "Test Strategy",
        config_json: dict[str, Any] | None = None,
    ) -> tuple[Strategy, StrategyVersion]:
        strategy = Strategy(
            id=uuid.uuid4(),
            user_id=uuid.UUID(user_id),
            name=strategy_name,
            description="Test strategy",
            strategy_type=StrategyType.SIMULATION,
            visibility="PRIVATE",
            status="ACTIVE",
        )
        db_session.add(strategy)
        db_session.commit()
        db_session.refresh(strategy)

        version = StrategyVersion(
            id=uuid.uuid4(),
            strategy_id=strategy.id,
            version_number=1,
            config_json=config_json or _default_strategy_config(),
            config_hash="test-config-hash",
            change_note="initial",
            created_by_user_id=uuid.UUID(user_id),
        )
        db_session.add(version)
        db_session.commit()
        db_session.refresh(version)

        strategy.current_version_id = version.id
        db_session.commit()
        db_session.refresh(strategy)

        return strategy, version

    return _create_strategy_bundle