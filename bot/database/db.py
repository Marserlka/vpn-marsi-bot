from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.config import settings
from bot.database.models import Base

engine = create_async_engine(settings.DB_URL, echo=False)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def _add_missing_columns(sync_conn) -> None:
    """SQLAlchemy's create_all() only creates missing tables, not missing
    columns on tables that already exist. Since we don't run Alembic
    migrations, patch existing SQLite tables in place so new model fields
    (e.g. Subscription.awg_public_key/awg_config, added when AmneziaWG
    became the primary protocol) show up on an already-deployed DB.
    """
    inspector = inspect(sync_conn)
    for table in Base.metadata.tables.values():
        if table.name not in inspector.get_table_names():
            continue
        existing = {col["name"] for col in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing:
                continue
            col_type = column.type.compile(sync_conn.dialect)
            sync_conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'))


def _backfill_connection_defaults(sync_conn) -> None:
    """`_add_missing_columns` adds new columns with no value on existing
    rows (Python-side `default=` doesn't apply retroactively) — give
    pre-existing connections a sane `name`/`region` instead of NULL."""
    sync_conn.exec_driver_sql(
        "UPDATE subscriptions SET name = 'Подключение' WHERE name IS NULL"
    )
    sync_conn.exec_driver_sql(
        "UPDATE subscriptions SET region = 'nl' WHERE region IS NULL"
    )


def _drop_subscriptions_user_unique(sync_conn) -> None:
    """The `subscriptions` table (now the `Connection` model) originally had
    `user_id UNIQUE` from the 1-subscription-per-user era (see TZ 3.5) — a
    second connection for the same user now needs to insert fine, so drop
    any unique index covering just that column on an already-deployed DB.
    """
    rows = sync_conn.exec_driver_sql("PRAGMA index_list('subscriptions')").fetchall()
    for row in rows:
        index_name, is_unique = row[1], row[2]
        if not is_unique:
            continue
        cols = sync_conn.exec_driver_sql(f'PRAGMA index_info("{index_name}")').fetchall()
        if [c[2] for c in cols] == ["user_id"]:
            sync_conn.exec_driver_sql(f'DROP INDEX "{index_name}"')


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)
        await conn.run_sync(_backfill_connection_defaults)
        await conn.run_sync(_drop_subscriptions_user_unique)
