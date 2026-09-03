from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import settings


def main_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🌐 Личный кабинет", callback_data="menu:profile")
    kb.button(text="🌐 Создать подключение", callback_data="menu:buy")
    kb.button(text="⚙️ Управление подключениями", callback_data="menu:manage")
    kb.button(text="📥 Инструкции", callback_data="menu:instructions")
    kb.button(text="🆘 Поддержка", callback_data="menu:support")
    kb.button(text="🎁 Бонус за друга", callback_data="menu:referral")
    kb.button(text="⭐ Купить звёзды", url=settings.STAR_BOT_URL)
    kb.adjust(1)
    return kb.as_markup()


def profile_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⚙️ Управление подключениями", callback_data="menu:manage")
    kb.button(text="⬅️ Главное меню", callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


def manage_keyboard(has_config: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if has_config:
        kb.button(text="📥 Получить конфиг", callback_data="menu:get_config")
    kb.button(text="🌐 Создать / продлить подключение", callback_data="menu:buy")
    kb.button(text="⬅️ Главное меню", callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


def back_to_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Главное меню", callback_data="menu:main")
    return kb.as_markup()


def plans_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for idx, plan in enumerate(settings.plans):
        kb.button(text=f"{plan.period_days} дн. — {plan.price_rub} руб.", callback_data=f"buy:plan:{idx}")
    kb.button(text="⬅️ Главное меню", callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


def promo_prompt_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Ввести промокод", callback_data="buy:promo")
    kb.button(text="Пропустить", callback_data="buy:skip_promo")
    kb.adjust(1)
    return kb.as_markup()


def payment_methods_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
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
