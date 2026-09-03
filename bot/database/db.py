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


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)
