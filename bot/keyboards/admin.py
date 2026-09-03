from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def admin_main_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📊 Статистика", callback_data="admin:stats")
    kb.button(text="👤 Управление пользователями", callback_data="admin:users")
    kb.button(text="🎟 Промокоды", callback_data="admin:promo")
    kb.button(text="📢 Рассылка", callback_data="admin:broadcast")
    kb.button(text="🔒 Обязательная подписка", callback_data="admin:force_sub")
    kb.adjust(1)
    return kb.as_markup()


def force_sub_keyboard(enabled: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if enabled:
        kb.button(text="🔴 Отключить", callback_data="admin:force_sub:disable")
    else:
        kb.button(text="🟢 Включить", callback_data="admin:force_sub:enable")
    kb.button(text="✏️ Задать канал", callback_data="admin:force_sub:set")
    kb.button(text="⬅️ Админ-меню", callback_data="admin:main")
    kb.adjust(1)
    return kb.as_markup()


def back_to_admin() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Админ-меню", callback_data="admin:main")
    return kb.as_markup()


def payment_confirmation_keyboard(payment_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Подтвердить оплату", callback_data=f"admin:confirm_payment:{payment_id}")
    kb.button(text="❌ Отклонить", callback_data=f"admin:reject_payment:{payment_id}")
    kb.adjust(1)
    return kb.as_markup()


def user_actions_keyboard(user_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Продлить на 30 дн.", callback_data=f"admin:extend:{user_id}:30")
    kb.button(text="⛔ Отключить", callback_data=f"admin:disable:{user_id}")
    kb.button(text="💳 Пополнить баланс", callback_data=f"admin:topup:{user_id}")
    kb.button(text="⬅️ Админ-меню", callback_data="admin:main")
    kb.adjust(1)
    return kb.as_markup()
