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
    MARZBAN_SNI_MASK: str = "vk.com"

    PLAN_1: str = "30:30"
    PLAN_2: str = "90:90"
    PLAN_3: str = "180:180"

    REFERRAL_BONUS_DAYS: int = 0
    REFERRAL_BONUS_AMOUNT: int = 15

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
