from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String, Boolean, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    tg_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Float, not Integer, since 2026-09-05 — the per-day billing model bills
    # fractional rubles (1.5/day/connection). SQLite doesn't enforce column
    # affinity strictly enough to need a real ALTER for this: existing whole
    # rubles keep reading back fine, new fractional writes store as REAL.
    balance: Mapped[float] = mapped_column(Float, default=0.0)
    referrer_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.tg_id"), nullable=True)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    # Legacy — the 3-day free-trial connection this gated was replaced by a
    # flat WELCOME_BONUS_RUB balance credit at registration (2026-09-05, see
    # bot/handlers/start.py and TZ). Column kept so old rows aren't destroyed;
    # nothing reads or writes it anymore.
    trial_used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())

    connections: Mapped[list["Connection"]] = relationship(back_populates="user")


class Connection(Base):
    """One VPN connection (peer/user on the server side). A user can have
    several of these at once (see TZ 3.5) — each is its own paid, named,
    independently-managed VPN identity, not tied to the others.

    Billing switched from prepaid periods to per-day debits on 2026-09-05
    (see TZ) — `expires_at` is legacy (kept only so old rows aren't
    destroyed, and as the seed value `next_charge_at` was backfilled from,
    see db.py:_backfill_next_charge_at) and is no longer written to.
    `next_charge_at` is the actual billing cursor: bot/scheduler/jobs.py's
    daily_billing() charges PRICE_PER_DAY_RUB from the owner's balance for
    every active connection whose next_charge_at has passed, then pushes it
    a day forward (see bot/services/subscriptions.py:charge_connection_day).
    reminder_3d_sent/reminder_1d_sent are likewise legacy — there's no more
    fixed expiry to remind anyone about.
    """

    __tablename__ = "subscriptions"  # kept for continuity with existing data/migrations

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.tg_id"))
    name: Mapped[str] = mapped_column(String(64), default="Подключение")
    region: Mapped[str] = mapped_column(String(16), default="de")  # only "de" for now
    marzban_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    subscription_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    awg_public_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    awg_config: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    protocol: Mapped[str] = mapped_column(String(16), default="amnezia")  # amnezia/wireguard/vless/ss
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    next_charge_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="inactive")  # inactive/active/expired
    reminder_3d_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    reminder_1d_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="connections")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.tg_id"))
    amount: Mapped[int] = mapped_column(Integer)
    period_days: Mapped[int] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending/paid/failed
    purpose: Mapped[str] = mapped_column(String(16), default="subscription")  # subscription/balance_topup
    # Which connection this pays for. Null when creating a brand-new one
    # (it doesn't exist yet — apply_paid_payment creates it) or for a
    # balance top-up (no connection involved at all).
    connection_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("subscriptions.id"), nullable=True)
    new_connection_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    new_connection_protocol: Mapped[str | None] = mapped_column(String(16), nullable=True)
    promo_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    invoice_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
    paid_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)


class PromoCode(Base):
    __tablename__ = "promo_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    discount_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    discount_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_activations: Mapped[int] = mapped_column(Integer, default=1)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())


class PromoActivation(Base):
    __tablename__ = "promo_activations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    promo_id: Mapped[int] = mapped_column(Integer, ForeignKey("promo_codes.id"))
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.tg_id"))
    used_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())


class ReferralBonus(Base):
    """Reworked twice on 2026-09-05 (see TZ): first from a cash percentage
    to a flat bonus_days-only payout, then — same day — back to cash, now a
    flat bonus_amount (REFERRAL_BONUS_RUB), granted once per referred user
    the first time they top up their balance (see
    bot/services/referrals.py:grant_referral_bonus_if_first_topup). The
    existence of a row for a given referred_id IS the dedup check, so
    bonus_amount is never actually 0 going forward. bonus_days and
    connection_id are both legacy from the brief days-based iteration —
    always 0/NULL on new rows, kept only so old rows aren't destroyed."""

    __tablename__ = "referral_bonuses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    referrer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.tg_id"))
    referred_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.tg_id"))
    bonus_days: Mapped[int] = mapped_column(Integer, default=0)
    bonus_amount: Mapped[int] = mapped_column(Integer, default=0)
    connection_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("subscriptions.id"), nullable=True)
    granted_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())


class BotSettings(Base):
    """Singleton row (id=1) of runtime settings the admin can change from
    inside the bot itself, without a redeploy — mandatory-channel-subscription
    gate, and the site-wide free period (see bot/services/free_period.py)."""

    __tablename__ = "bot_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    force_sub_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    force_sub_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    force_sub_channel_url: Mapped[str | None] = mapped_column(String(256), nullable=True)
    free_period_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    free_period_started_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)


class OlcRtcLabConfig(Base):
    """Singleton row (id=1) for the admin-only /test lab (bot/handlers/test.py)
    — currently just remembers the manually-created Yandex Telemost
    conference/key/port for the OlcRTC whitelist-bypass experiment (see TZ),
    so the admin doesn't have to keep them in a notes app. Nothing here is
    ever shown to a regular user or wired into the real protocol pickers."""

    __tablename__ = "olcrtc_lab_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conference_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    encryption_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    socks5_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(String(512), nullable=True)
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)


class BalanceTransaction(Base):
    __tablename__ = "balance_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.tg_id"))
    delta: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String(32))  # admin_topup / referral / topup / daily_charge
    created_by_admin_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
