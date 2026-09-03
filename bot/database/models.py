from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Boolean, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    tg_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    balance: Mapped[int] = mapped_column(Integer, default=0)
    referrer_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.tg_id"), nullable=True)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())

    subscription: Mapped["Subscription"] = relationship(back_populates="user", uselist=False)


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.tg_id"), unique=True)
    marzban_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    subscription_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    awg_public_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    awg_config: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    protocol: Mapped[str] = mapped_column(String(16), default="amnezia")  # amnezia/wireguard
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="inactive")  # inactive/active/expired
    reminder_3d_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    reminder_1d_sent: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped["User"] = relationship(back_populates="subscription")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.tg_id"))
    amount: Mapped[int] = mapped_column(Integer)
    period_days: Mapped[int] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending/paid/failed
    purpose: Mapped[str] = mapped_column(String(16), default="subscription")  # subscription/balance_topup
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
    __tablename__ = "referral_bonuses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    referrer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.tg_id"))
    referred_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.tg_id"))
    bonus_days: Mapped[int] = mapped_column(Integer, default=0)
    bonus_amount: Mapped[int] = mapped_column(Integer, default=0)
    granted_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())


class BotSettings(Base):
    """Singleton row (id=1) of runtime settings the admin can change from
    inside the bot itself, without a redeploy — currently just the
    mandatory-channel-subscription gate."""

    __tablename__ = "bot_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    force_sub_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    force_sub_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    force_sub_channel_url: Mapped[str | None] = mapped_column(String(256), nullable=True)


class BalanceTransaction(Base):
    __tablename__ = "balance_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.tg_id"))
    delta: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(32))  # admin_topup / referral / purchase
    created_by_admin_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
