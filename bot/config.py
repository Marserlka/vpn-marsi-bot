from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    BOT_TOKEN: str
    ADMIN_IDS: str = ""

    DB_URL: str = "sqlite+aiosqlite:///./vpn_marsi.db"

    MARZBAN_BASE_URL: str = ""
    MARZBAN_ADMIN_USERNAME: str = ""
    MARZBAN_ADMIN_PASSWORD: str = ""
    MARZBAN_INBOUND_TAG: str = "VLESS-Reality"
    MARZBAN_SS_INBOUND_TAG: str = "Shadowsocks-TCP"
    MARZBAN_SNI_MASK: str = "sap.com"

    # AmneziaWG peer-management agent (default protocol — see TZ 3.2 for why
    # VLESS-Reality was originally demoted, and TZ 3.4 for why it's back as
    # an alternative alongside Shadowsocks, both via Marzban/Xray).
    AWG_AGENT_BASE_URL: str = ""
    AWG_AGENT_TOKEN: str = ""

    # Per-day billing (replaced the old prepaid 1/2/3-month PLAN_1/2/3 tariffs
    # on 2026-09-05 — see TZ). Each active connection independently costs
    # PRICE_PER_DAY_RUB/day, debited from the owner's balance by the
    # scheduler (bot/scheduler/jobs.py:daily_billing) via
    # bot/services/subscriptions.py:charge_connection_day. Two connections
    # cost 2x/day, three cost 3x/day, etc. Insufficient balance at charge
    # time disables the connection immediately (no grace period).
    PRICE_PER_DAY_RUB: float = 1.5

    # One-time-only free trial (see bot/services/subscriptions.py
    # create_connection(trial=True)) — gated by User.trial_used so it can't
    # be repeated by the same account. A trial connection accrues no daily
    # charge for its first TRIAL_DAYS days, then bills normally.
    TRIAL_DAYS: int = 3

    # A connection younger than this can't be deleted by its owner (see
    # bot/handlers/profile.py disable_confirm/disable_do) — disclosed to the
    # user during the creation wizard (bot/keyboards/client.py
    # create_confirm_keyboard). Doesn't apply to admin- or
    # scheduler-initiated deactivation (insufficient balance).
    MIN_CONNECTION_AGE_DAYS: int = 7

    # Referral: as of 2026-09-05, a flat one-time cash bonus credited to the
    # referrer's balance the first time (and only the first time) their
    # referral tops up their own balance — see bot/services/referrals.py.
    # Guarded by an "I'm not a bot" captcha button in /start so ref-farming
    # bots can't cheaply spam referral signups.
    REFERRAL_BONUS_RUB: float = 10
    REFERRAL_CAPTCHA_TIMEOUT_SECONDS: int = 120

    SUPPORT_USERNAME: str = "Marserlka"

    # Legal documents shown before purchase (required for payment-provider
    # compliance — see TZ). Update these if the docs are republished elsewhere.
    PRIVACY_POLICY_URL: str = "https://telegra.ph/Politika-konfidencialnosti-09-03-91"
    TERMS_URL: str = "https://telegra.ph/Polzovatelskoe-soglashenie-09-03-40"

    @property
    def admin_ids(self) -> set[int]:
        return {int(x) for x in self.ADMIN_IDS.split(",") if x.strip()}


settings = Settings()
