"""
alembic/env.py — Configures Alembic to use our async SQLAlchemy engine.

WHY async env.py:
  Our engine uses asyncpg (async). Alembic's default env.py is synchronous.
  We use run_sync() to run Alembic's synchronous migration code on an async
  connection — the standard approach for async SQLAlchemy.

WHY import all models:
  Alembic reads Base.metadata to know what tables exist. If models aren't
  imported, Alembic won't know about them and will generate empty migrations.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

# Import Base and all models so Alembic discovers the schema
from app.database import Base
import app.models  # noqa: F401 — side-effect: registers all models with Base

from app.config import settings

# Alembic Config object — provides access to alembic.ini values
config = context.config

# Set up Python logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The metadata Alembic uses to compare against the live DB
target_metadata = Base.metadata


def do_run_migrations(connection):
    """Run migrations synchronously (required by Alembic)."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online():
    """
    Run migrations with an async engine.
    Alembic can't drive an async connection directly, so we use run_sync()
    to call the synchronous migration runner on the async connection.
    """
    connectable = create_async_engine(settings.database_url, future=True)

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


# Offline mode (generate SQL without a live DB) — not used in Docker workflow
def run_migrations_offline():
    url = settings.database_url
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
