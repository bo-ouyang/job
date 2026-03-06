from __future__ import annotations

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


from jobCollectionWebApi.config import settings  # noqa: E402
from common.databases import models  # noqa: F401,E402
from common.databases.models.base import Base as CoreBase  # noqa: E402
from common.databases.models.city import Base as CityBase  # noqa: E402
from common.databases.models.city_hot import Base as CityHotBase  # noqa: E402


if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Use project settings to avoid duplicating DB config in alembic.ini
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL_SYNC)

# Note:
# city.py and city_hot.py currently use independent Base() definitions,
# so we include all metadata objects here for autogenerate compatibility.
target_metadata = [CoreBase.metadata, CityBase.metadata, CityHotBase.metadata]


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        compare_server_default=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
