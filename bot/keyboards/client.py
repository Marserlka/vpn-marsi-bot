from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import settings

PROTOCOL_CHOICES = {
    "amnezia": "AmneziaWG (маскировка)",
    "wireguard": "WireGuard (скорость)",
    "vless": "VLESS-Reality",
    "ss": "Shadowsocks",
}
REGION_CHOICES = {"nl": "🇳🇱 Нидерланды"}


def main_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🌐 Личный кабинет", callback_data="menu:profile")
    kb.button(text="📡 Мои подключения", callback_data="menu:connections")
    kb.button(text="💰 Баланс", callback_data="menu:balance")
    kb.button(text="📥 Инструкции", callback_data="menu:instructions")
    kb.button(text="🆘 Поддержка", callback_data="menu:support")
    kb.button(text="🎁 Бонус за друга", callback_data="menu:referral")
    kb.button(text="📄 Политика / Условия", callback_data="menu:legal")
    kb.adjust(1)
    return kb.as_markup()


def profile_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📡 Мои подключения", callback_data="menu:connections")
    kb.button(text="➕ Создать подключение", callback_data="create:start")
    kb.button(text="⬅️ Главное меню", callback_data="menu:main")
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


def connection_card_keyboard(conn) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if conn.status == "active":
        kb.button(text="📥 Получить конфиг", callback_data=f"menu:get_config:{conn.id}")
        kb.button(text="🔄 Обновить конфиг", callback_data=f"menu:regen:{conn.id}")
        kb.button(text="🔀 Сменить протокол", callback_data=f"menu:switch:{conn.id}")
        kb.button(text="⛔ Отключить", callback_data=f"menu:disable:{conn.id}")
    kb.button(text="➕ Продлить", callback_data=f"menu:extend:{conn.id}")
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


def plans_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for idx, plan in enumerate(settings.plans):
        kb.button(text=f"{plan.period_days} дн. — {plan.price_rub} руб.", callback_data=f"buy:plan:{idx}")
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
