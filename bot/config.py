from __future__ import annotations

from dataclasses import dataclass, field

from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True)
class Plan:
    period_days: int
    price_rub: int


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

    PLAN_1: str = "30:50"
    PLAN_2: str = "60:100"
    PLAN_3: str = "90:150"

    # One-time-only free trial (see bot/services/subscriptions.py
    # create_trial_connection) — gated by User.trial_used so it can't be
    # repeated by the same account.
    TRIAL_DAYS: int = 3

    # Referral: as of 2026-09-05, no cash payout — a flat REFERRAL_BONUS_DAYS
    # bonus, credited on EACH of the referred user's payments (not just the
    # first), that the referrer picks which of their own connections to add
    # to (see bot/services/referrals.py). Guarded by an "I'm not a bot"
    # captcha button in /start so ref-farming bots can't cheaply spam
    # referral signups.
    REFERRAL_BONUS_DAYS: int = 3
    REFERRAL_CAPTCHA_TIMEOUT_SECONDS: int = 120

    SUPPORT_USERNAME: str = "Marserlka"

    # Legal documents shown before purchase (required for payment-provider
    # compliance — see TZ). Update these if the docs are republished elsewhere.
    PRIVACY_POLICY_URL: str = "https://telegra.ph/Politika-konfidencialnosti-09-03-91"
    TERMS_URL: str = "https://telegra.ph/Polzovatelskoe-soglashenie-09-03-40"

    REMINDER_DAYS_BEFORE: str = "3,1"

    @property
    def admin_ids(self) -> set[int]:
        return {int(x) for x in self.ADMIN_IDS.split(",") if x.strip()}

    @property
    def plans(self) -> list[Plan]:
        raw = [self.PLAN_1, self.PLAN_2, self.PLAN_3]
        result = []
        for item in raw:
            days_str, price_str = item.split(":")
            result.append(Plan(period_days=int(days_str), price_rub=int(price_str)))
        return result

    @property
    def reminder_days_before(self) -> list[int]:
        return [int(x) for x in self.REMINDER_DAYS_BEFORE.split(",") if x.strip()]


settings = Settings()
