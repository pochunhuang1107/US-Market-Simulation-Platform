from logging.config import fileConfig
import os

from sqlalchemy import engine_from_config, pool
from alembic import context

from market_simulator.db.base import Base
from market_simulator.db import models  # IMPORTANT (loads all models)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Load DB URL from env
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/market_simulator"
)

config.set_main_option("sqlalchemy.url", DATABASE_URL)

target_metadata = Base.metadata


def run_migrations_offline():
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()