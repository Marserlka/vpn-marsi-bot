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
    builder.button(text="Пополнить баланс", callback_data="balance:topup", icon_custom_emoji_id=PE_ID["price"])
    builder.button(text="⬅️ Главное меню", callback_data="menu:main")
    builder.adjust(1, 1, 1, 1)
    return builder.as_markup()


def connections_list_keyboard(connections: list) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for conn in connections:
        icon = "✅" if conn.status == "active" else "❌"
        kb.button(text=f"{icon} {conn.name}", callback_data=f"menu:connection:{conn.id}")
    kb.button(text="Создать подключение", callback_data="create:start", icon_custom_emoji_id=PE_ID["add_connection"])
    kb.button(text="⬅️ Главное меню", callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


def connection_card_keyboard(conn) -> InlineKeyboardMarkup:
    # "Продлить" removed 2026-09-05 (subscriptions are billed per-day from
    # balance now, there's nothing to buy more of — see TZ) — disable/delete
    # still uses the same menu:disable:* flow under the hood, just relabeled
    # "Удалить" per the new icon set.
    kb = InlineKeyboardBuilder()
    if conn.status == "active":
        kb.button(text="Получить конфиг", callback_data=f"menu:get_config:{conn.id}", icon_custom_emoji_id=PE_ID["get_config"])
        kb.button(text="📱 QR-код", callback_data=f"menu:qr:{conn.id}")
        kb.button(text="Обновить конфиг", callback_data=f"menu:regen:{conn.id}", icon_custom_emoji_id=PE_ID["update_config"])
        kb.button(text="Сменить протокол", callback_data=f"menu:switch:{conn.id}", icon_custom_emoji_id=PE_ID["switch_protocol"])
        # Subscription-URL delivery (2026-09-05) bundles multiple per-inbound
        # keys behind one link — this lets advanced users grab them
        # individually instead of relying on the client's subscription import.
        if conn.protocol in ("vless", "ss"):
            kb.button(text="🔑 VLESS ключи", callback_data=f"menu:vless_keys:{conn.id}")
        kb.button(text="Удалить", callback_data=f"menu:disable:{conn.id}", icon_custom_emoji_id=PE_ID["delete"])
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
    kb.button(text="Пополнить", callback_data="balance:topup", icon_custom_emoji_id=PE_ID["price"])
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


def create_confirm_keyboard(show_trial: bool = False) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if show_trial:
        kb.button(text=f"🎁 Пробный период ({settings.TRIAL_DAYS} дня, бесплатно)", callback_data="create:trial")
    kb.button(text="Создать подключение", callback_data="create:confirm", icon_custom_emoji_id=PE_ID["add_connection"])
    kb.button(text="Политика / Условия", callback_data="buy:legal", icon_custom_emoji_id=PE_ID["legal"])
    kb.button(text="⬅️ Отмена", callback_data="menu:connections")
    kb.adjust(1)
    return kb.as_markup()


def legal_docs_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Политика конфиденциальности", url=settings.PRIVACY_POLICY_URL, icon_custom_emoji_id=PE_ID["legal"])
    kb.button(text="Условия использования", url=settings.TERMS_URL, icon_custom_emoji_id=PE_ID["legal"])
    kb.button(text="⬅️ Главное меню", callback_data="menu:main")
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
