from __future__ import annotations

import datetime as dt

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.config import settings
from bot.database.models import Base, Connection

engine = create_async_engine(settings.DB_URL, echo=False)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def _add_missing_columns(sync_conn) -> set[tuple[str, str]]:
    """SQLAlchemy's create_all() only creates missing tables, not missing
    columns on tables that already exist. Since we don't run Alembic
    migrations, patch existing SQLite tables in place so new model fields
    (e.g. Subscription.awg_public_key/awg_config, added when AmneziaWG
    became the primary protocol) show up on an already-deployed DB.

    Returns the (table, column) pairs actually added *this run*, so a
    one-off backfill (see _backfill_legacy_referral_bonuses) can tell "just
    added, still empty" apart from "existed already, may have real data" —
    this function itself runs on every boot, so it can't assume "column is
    empty" means "column is new".
    """
    added: set[tuple[str, str]] = set()
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
            added.add((table.name, column.name))
    return added


def _backfill_legacy_referral_bonuses(sync_conn, added_columns: set[tuple[str, str]]) -> None:
    """referral_bonuses.connection_id NULL means "pending, referrer hasn't
    picked a connection yet" (see the ReferralBonus model docstring and
    bot/services/referrals.py) — but every row that existed *before* this
    column was added would also read as NULL, which would let referrers
    re-claim bonus days they already received under the old (auto-applied)
    logic. Only when this boot is the one that actually added the column do
    we stamp every pre-existing row with a non-NULL sentinel (-1, "legacy,
    already settled, not claimable"); bonuses granted after that point go
    through the normal pending flow untouched.
    """
    if ("referral_bonuses", "connection_id") not in added_columns:
        return
    sync_conn.exec_driver_sql(
        "UPDATE referral_bonuses SET connection_id = -1 WHERE connection_id IS NULL"
    )


def _backfill_next_charge_at(sync_conn, added_columns: set[tuple[str, str]]) -> None:
    """New per-connection daily-billing cursor (2026-09-05 switch from
    prepaid monthly plans to a PRICE_PER_DAY_RUB/day charge per connection
    — see TZ and the Connection model docstring). `_add_missing_columns`
    leaves it NULL on every pre-existing row; if this boot is the one that
    added the column, seed active connections from whatever `expires_at`
    they already had (so nobody who prepaid a period under the old model
    loses that time to the new daily debit) instead of starting the daily
    clock immediately for everyone. Connections created after this point
    always get next_charge_at set explicitly at creation time, so this only
    ever fires once, on the boot that runs the migration.
    """
    if ("subscriptions", "next_charge_at") not in added_columns:
        return
    sync_conn.execute(
        text(
            'UPDATE subscriptions SET next_charge_at = COALESCE("expires_at", :now) '
            'WHERE status = \'active\' AND next_charge_at IS NULL'
        ),
        {"now": dt.datetime.utcnow()},
    )


def _backfill_connection_defaults(sync_conn) -> None:
    """`_add_missing_columns` adds new columns with no value on existing
    rows (Python-side `default=` doesn't apply retroactively) — give
    pre-existing connections real values instead of NULL for every
    NOT NULL column, so the table-rebuild in `_drop_subscriptions_user_unique`
    (which needs this already clean) doesn't have to special-case anything.
    Uses bound parameters, not string-formatted SQL — inlining non-ASCII
    literals (e.g. "Подключение") into raw SQL text has a real encoding
    footgun, confirmed by testing this migration locally.
    """
    inspector = inspect(sync_conn)
    if "subscriptions" not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns("subscriptions")}
    for column in Connection.__table__.columns:
        if column.nullable or column.name not in existing:
            continue
        if column.name == "created_at":
            sync_conn.exec_driver_sql(
                'UPDATE subscriptions SET "created_at" = CURRENT_TIMESTAMP WHERE "created_at" IS NULL'
            )
        elif column.default is not None and getattr(column.default, "is_scalar", False):
            sync_conn.execute(
                text(f'UPDATE subscriptions SET "{column.name}" = :val WHERE "{column.name}" IS NULL'),
                {"val": column.default.arg},
            )


def _drop_subscriptions_user_unique(sync_conn) -> None:
    """The `subscriptions` table (now the `Connection` model) originally had
    `user_id UNIQUE` from the 1-subscription-per-user era (see TZ 3.5) — a
    second connection for the same user now needs to insert fine.

    SQLite auto-creates an index for a `UNIQUE` declared inline on a column
    (origin='u'); that kind of index can't be dropped with `DROP INDEX` —
    it's intrinsic to the table definition ("index associated with UNIQUE
    or PRIMARY KEY constraint cannot be dropped"). The only way to remove
    it is to rebuild the table without the constraint, so that's what this
    does when it detects that case; a plain `CREATE UNIQUE INDEX` (origin=
    'c', from some earlier ad-hoc migration) can just be dropped directly.
    """
    rows = sync_conn.exec_driver_sql("PRAGMA index_list('subscriptions')").fetchall()
    target = None
    for row in rows:
        index_name, is_unique, origin = row[1], row[2], row[3]
        if not is_unique:
            continue
        cols = sync_conn.exec_driver_sql(f'PRAGMA index_info("{index_name}")').fetchall()
        if [c[2] for c in cols] == ["user_id"]:
            target = (index_name, origin)
            break
    if target is None:
        return

    index_name, origin = target
    if origin != "u":
        sync_conn.exec_driver_sql(f'DROP INDEX "{index_name}"')
        return

    # By this point `_backfill_connection_defaults` has already run, so every
    # NOT NULL column is populated — a plain column-for-column copy is safe.
    inspector = inspect(sync_conn)
    old_columns = {col["name"] for col in inspector.get_columns("subscriptions")}
    shared = [c.name for c in Connection.__table__.columns if c.name in old_columns]
    cols_sql = ", ".join(f'"{c}"' for c in shared)

    sync_conn.exec_driver_sql("ALTER TABLE subscriptions RENAME TO subscriptions_old")
    Connection.__table__.create(sync_conn)
    sync_conn.exec_driver_sql(
        f'INSERT INTO subscriptions ({cols_sql}) SELECT {cols_sql} FROM subscriptions_old'
    )
    sync_conn.exec_driver_sql("DROP TABLE subscriptions_old")


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        added_columns = await conn.run_sync(_add_missing_columns)
        await conn.run_sync(_backfill_connection_defaults)
        await conn.run_sync(_drop_subscriptions_user_unique)
        await conn.run_sync(lambda c: _backfill_legacy_referral_bonuses(c, added_columns))
        await conn.run_sync(lambda c: _backfill_next_charge_at(c, added_columns))
