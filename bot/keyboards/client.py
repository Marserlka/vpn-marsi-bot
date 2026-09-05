from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import settings
from bot.keyboards._helpers import do_ikb
from bot.utils.emoji import PE_ID

# WireGuard and Shadowsocks temporarily hidden from new-connection/protocol-
# switch pickers (2026-09-05, admin request) — existing connections on
# either protocol keep working as-is (profile.py's PROTOCOL_LABELS is a
# separate dict and still has both), this only stops new ones being chosen.
PROTOCOL_CHOICES = {
    "amnezia": "AmneziaWG (маскировка)",
    "vless": "VLESS-Reality",
}
REGION_CHOICES = {"de": "🇩🇪 Германия"}


def main_menu(news_channel_url: str | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Личный кабинет", callback_data="menu:profile", icon_custom_emoji_id=PE_ID["cabinet"])
    builder.button(text="Пригласить друга", callback_data="menu:referral", icon_custom_emoji_id=PE_ID["invite"])
    builder.button(text="Поддержка", callback_data="menu:support", icon_custom_emoji_id=PE_ID["support"])
    layout = [1, 1, 1]
    if news_channel_url:
        builder.button(text="Новостной канал", url=news_channel_url, icon_custom_emoji_id=PE_ID["news"])
        layout[-1] = 2
    builder.button(text="Политика / Условия", callback_data="menu:legal", icon_custom_emoji_id=PE_ID["legal"])
    builder.button(text="Инструкции", callback_data="menu:instructions", icon_custom_emoji_id=PE_ID["instructions"])
    layout.append(2)
    builder.adjust(*layout)
    return builder.as_markup()


def profile_keyboard() -> InlineKeyboardMarkup:
    kb = do_ikb(
        ["Мои подключения", "Добавить подключение"],
        ["menu:connections", "create:start"],
        [1, 1],
        icons={0: PE_ID["connections"], 1: PE_ID["add_connection"]},
    )
    builder = InlineKeyboardBuilder.from_markup(kb)
    builder.button(text="💰 Пополнить баланс", callback_data="balance:topup")
    builder.button(text="⬅️ Главное меню", callback_data="menu:main")
    builder.adjust(1, 1, 1, 1)
    return builder.as_markup()


def referral_bonus_keyboard(connections: list) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for conn in connections:
        kb.button(text=conn.name, callback_data=f"refbonus:apply:{conn.id}")
    kb.adjust(1)
    return kb.as_markup()


def connections_list_keyboard(connections: list) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for conn in connections:
        icon = "✅" if conn.status == "active" else "❌"
        kb.button(text=f"{icon} {conn.name}", callback_data=f"menu:connection:{conn.id}")
    kb.button(text="➕ Создать подключение", callback_data="create:start")
    kb.button(text="⬅️ Главное меню", callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


def connection_card_keyboard(conn, pending_bonus_days: int = 0) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if conn.status == "active":
        kb.button(text="📥 Получить конфиг", callback_data=f"menu:get_config:{conn.id}")
        kb.button(text="🔄 Обновить конфиг", callback_data=f"menu:regen:{conn.id}")
        kb.button(text="🔀 Сменить протокол", callback_data=f"menu:switch:{conn.id}")
        kb.button(text="⛔ Отключить", callback_data=f"menu:disable:{conn.id}")
    kb.button(text="➕ Продлить", callback_data=f"menu:extend:{conn.id}")
    if pending_bonus_days:
        kb.button(text=f"🎁 Добавить {pending_bonus_days} реф. дн.", callback_data=f"refbonus:apply:{conn.id}")
    kb.button(text="⬅️ К списку", callback_data="menu:connections")
    kb.adjust(1)
    return kb.as_markup()


def protocol_switch_keyboard(conn) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for proto, label in PROTOCOL_CHOICES.items():
        if proto == conn.protocol:
            continue
        kb.button(text=label, callback_data=f"menu:switch_do:{conn.id}:{proto}")
    kb.button(text="⬅️ Назад", callback_data=f"menu:connection:{conn.id}")
    kb.adjust(1)
    return kb.as_markup()


def balance_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Пополнить", callback_data="balance:topup")
    kb.button(text="⬅️ Главное меню", callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


def back_to_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Главное меню", callback_data="menu:main")
    return kb.as_markup()


def create_protocol_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for proto, label in PROTOCOL_CHOICES.items():
        kb.button(text=label, callback_data=f"create:protocol:{proto}")
    kb.button(text="⬅️ Отмена", callback_data="menu:connections")
    kb.adjust(1)
    return kb.as_markup()


def create_region_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for region, label in REGION_CHOICES.items():
        kb.button(text=label, callback_data=f"create:region:{region}")
    kb.button(text="⬅️ Отмена", callback_data="menu:connections")
    kb.adjust(1)
    return kb.as_markup()


PLAN_PERIOD_LABELS = {30: "1 месяц", 60: "2 месяца", 90: "3 месяца"}


def plan_period_label(period_days: int) -> str:
    return PLAN_PERIOD_LABELS.get(period_days, f"{period_days} дн.")


def plans_keyboard(show_trial: bool = False) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if show_trial:
        kb.button(text=f"🎁 Пробный период ({settings.TRIAL_DAYS} дня, бесплатно)", callback_data="buy:trial")
    for idx, plan in enumerate(settings.plans):
        kb.button(text=f"{plan_period_label(plan.period_days)} — {plan.price_rub} руб.", callback_data=f"buy:plan:{idx}")
    kb.button(text="📄 Политика / Условия", callback_data="buy:legal")
    kb.button(text="⬅️ Назад", callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


def legal_docs_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔒 Политика конфиденциальности", url=settings.PRIVACY_POLICY_URL)
    kb.button(text="📄 Условия использования", url=settings.TERMS_URL)
    kb.button(text="⬅️ Главное меню", callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


def promo_prompt_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Ввести промокод", callback_data="buy:promo")
    kb.button(text="Пропустить", callback_data="buy:skip_promo")
    kb.adjust(1)
    return kb.as_markup()


def payment_methods_keyboard(can_pay_from_balance: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if can_pay_from_balance:
        kb.button(text="💰 Оплатить с баланса", callback_data="buy:pay:balance")
    kb.button(text="✅ Оплатить (тестовый режим)", callback_data="buy:pay:manual")
    kb.button(text="⬅️ Отмена", callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


def waiting_confirmation_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Я оплатил(а)", callback_data="buy:confirm_paid")
    kb.adjust(1)
    return kb.as_markup()


def captcha_keyboard(referrer_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Я не бот", callback_data=f"start:verify:{referrer_id}")
    return kb.as_markup()
