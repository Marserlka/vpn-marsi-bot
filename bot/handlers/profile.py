from __future__ import annotations

import random
import string

from aiogram import Router, F
from aiogram.types import BufferedInputFile, CallbackQuery
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.database.models import Connection, Payment, ReferralBonus, User
from bot.keyboards.client import (
    back_to_menu,
    connection_card_keyboard,
    connections_list_keyboard,
    profile_keyboard,
)
from bot.services.subscriptions import (
    MARZBAN_FAMILY,
    deactivate,
    get_connection,
    list_connections,
    regenerate_connection,
    switch_protocol,
)

router = Router(name="profile")

PROTOCOL_LABELS = {
    "amnezia": "AmneziaWG (маскировка)",
    "wireguard": "WireGuard (скорость)",
    "vless": "VLESS-Reality",
    "ss": "Shadowsocks",
}
PROTOCOL_APP = {
    "amnezia": "приложение AmneziaVPN",
    "wireguard": "официальное приложение WireGuard",
    "vless": "приложение v2rayNG / Happ / Streisand (поддерживающее VLESS)",
    "ss": "приложение Shadowsocks (Outline, NekoBox и т.п.)",
}
PROTOCOL_IMPORT_HINT = {
    "amnezia": "«Добавить конфигурацию» → «Импортировать из файла» → выберите этот файл",
    "wireguard": "«Добавить конфигурацию» → «Импортировать из файла» → выберите этот файл",
    "vless": "нажмите на ссылку выше, чтобы скопировать её, и добавьте в приложении («Добавить профиль по ссылке»)",
    "ss": "нажмите на ссылку выше, чтобы скопировать её, и добавьте в приложении («Добавить профиль по ссылке»)",
}
REGION_LABELS = {"de": "🇩🇪 Германия"}


def random_config_filename() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"NetherlMarsi-{suffix}.conf"


def _status_line(conn: Connection) -> str:
    if conn.status == "active" and conn.expires_at:
        return f"Статус: ✅ Активно до {conn.expires_at.strftime('%d.%m.%Y')}"
    return "Статус: ❌ Истекло"


def _connection_card_text(conn: Connection) -> str:
    limit_note = (
        "⚠️ Ограничение: 1 подключение = 1 устройство."
        if conn.protocol in ("amnezia", "wireguard")
        else "ℹ️ Для этого протокола ограничение на 1 устройство сейчас не действует."
    )
    return (
        f"📡 {conn.name}\n\n"
        f"{_status_line(conn)}\n"
        f"Протокол: {PROTOCOL_LABELS.get(conn.protocol, conn.protocol)}\n"
        f"Регион: {REGION_LABELS.get(conn.region, conn.region)}\n\n"
        f"{limit_note}"
    )


@router.callback_query(F.data == "menu:profile")
async def profile(callback: CallbackQuery, session: AsyncSession) -> None:
    user = await session.get(User, callback.from_user.id)
    conns = await list_connections(session, callback.from_user.id)
    active_count = sum(1 for c in conns if c.status == "active")

    text = (
        f"🌐 Личный кабинет\n\n"
        f"Баланс: {user.balance} руб.\n"
        f"Активных подключений: {active_count}\n\n"
        f"⚠️ Каждое подключение — 1 устройство."
    )
    await callback.message.edit_text(text, reply_markup=profile_keyboard())
    await callback.answer()


@router.callback_query(F.data == "menu:connections")
async def connections_list(callback: CallbackQuery, session: AsyncSession) -> None:
    conns = await list_connections(session, callback.from_user.id)
    text = "📡 Мои подключения" if conns else "📡 Мои подключения\n\nПока нет ни одного подключения."
    await callback.message.edit_text(text, reply_markup=connections_list_keyboard(conns))
    await callback.answer()


@router.callback_query(F.data.startswith("menu:connection:"))
async def connection_card(callback: CallbackQuery, session: AsyncSession) -> None:
    conn_id = int(callback.data.split(":")[-1])
    conn = await get_connection(session, conn_id, callback.from_user.id)
    if not conn:
        await callback.answer("Подключение не найдено.", show_alert=True)
        return
    await callback.message.edit_text(
        _connection_card_text(conn),
        reply_markup=connection_card_keyboard(conn),
    )
    await callback.answer()


async def send_connection_config(bot, chat_id: int, conn: Connection) -> None:
    """Delivers a connection's config the right way for its protocol:
    WireGuard/AmneziaWG need an importable .conf file; VLESS/Shadowsocks
    are a single link that's useless as a file attachment (Telegram won't
    preview it, so the user would have to download and open it just to
    copy one line) — send those as plain copyable text instead."""
    app_name = PROTOCOL_APP.get(conn.protocol, "приложение AmneziaVPN")
    import_hint = PROTOCOL_IMPORT_HINT.get(conn.protocol, PROTOCOL_IMPORT_HINT["amnezia"])
    limit_note = (
        "⚠️ 1 подключение = 1 устройство."
        if conn.protocol not in MARZBAN_FAMILY
        else "ℹ️ Ограничение на 1 устройство для этого протокола пока не действует."
    )
    header = f"«{conn.name}» — {PROTOCOL_LABELS.get(conn.protocol, conn.protocol)}."
    steps = f"1. Установите {app_name}.\n2. {import_hint}.\n3. Подключитесь.\n\n{limit_note}"

    if conn.protocol in MARZBAN_FAMILY:
        import html as html_lib

        text = f"{header}\n\n<code>{html_lib.escape(conn.awg_config)}</code>\n\n{steps}"
        await bot.send_message(chat_id, text, parse_mode="HTML")
    else:
        file = BufferedInputFile(conn.awg_config.encode(), filename=random_config_filename())
        await bot.send_document(chat_id, file, caption=f"{header}\n\n{steps}")


@router.callback_query(F.data.startswith("menu:get_config:"))
async def get_config(callback: CallbackQuery, session: AsyncSession) -> None:
    conn_id = int(callback.data.split(":")[-1])
    conn = await get_connection(session, conn_id, callback.from_user.id)
    if not conn or not conn.awg_config or conn.status != "active":
        await callback.answer("Нет активного конфига.", show_alert=True)
        return

    await send_connection_config(callback.bot, callback.message.chat.id, conn)
    await callback.answer()


@router.callback_query(F.data.startswith("menu:regen:"))
async def regen_confirm(callback: CallbackQuery, session: AsyncSession) -> None:
    conn_id = int(callback.data.split(":")[-1])
    conn = await get_connection(session, conn_id, callback.from_user.id)
    if not conn:
        await callback.answer("Подключение не найдено.", show_alert=True)
        return
    await callback.message.edit_text(
        f"Обновить конфиг «{conn.name}»?\n\n"
        "⚠️ Старый ключ сразу перестанет работать на всех устройствах, где он был "
        "установлен — понадобится импортировать новый файл.",
        reply_markup=_confirm_keyboard(f"menu:regen_do:{conn_id}", f"menu:connection:{conn_id}"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("menu:regen_do:"))
async def regen_do(callback: CallbackQuery, session: AsyncSession) -> None:
    conn_id = int(callback.data.split(":")[-1])
    conn = await get_connection(session, conn_id, callback.from_user.id)
    if not conn:
        await callback.answer("Подключение не найдено.", show_alert=True)
        return
    try:
        await regenerate_connection(session, conn)
    except Exception as exc:
        await callback.answer(f"Ошибка: {exc}", show_alert=True)
        raise
    await callback.answer("Конфиг обновлён", show_alert=True)
    await callback.message.edit_text(_connection_card_text(conn), reply_markup=connection_card_keyboard(conn))


@router.callback_query(F.data.startswith("menu:switch:"))
async def switch_protocol_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    conn_id = int(callback.data.split(":")[-1])
    conn = await get_connection(session, conn_id, callback.from_user.id)
    if not conn:
        await callback.answer("Подключение не найдено.", show_alert=True)
        return
    from bot.keyboards.client import protocol_switch_keyboard

    await callback.message.edit_text(
        f"Сменить протокол для «{conn.name}»:", reply_markup=protocol_switch_keyboard(conn)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("menu:switch_do:"))
async def switch_protocol_do(callback: CallbackQuery, session: AsyncSession) -> None:
    _, _, conn_id_str, new_protocol = callback.data.split(":")
    conn = await get_connection(session, int(conn_id_str), callback.from_user.id)
    if not conn:
        await callback.answer("Подключение не найдено.", show_alert=True)
        return
    try:
        await switch_protocol(session, conn, new_protocol)
    except ValueError:
        await callback.answer("Подключение неактивно.", show_alert=True)
        return
    except Exception as exc:
        await callback.answer(f"Ошибка: {exc}", show_alert=True)
        raise
    await callback.answer(f"Протокол изменён на {PROTOCOL_LABELS.get(new_protocol, new_protocol)}", show_alert=True)
    await callback.message.edit_text(_connection_card_text(conn), reply_markup=connection_card_keyboard(conn))


@router.callback_query(F.data.startswith("menu:disable:"))
async def disable_confirm(callback: CallbackQuery, session: AsyncSession) -> None:
    conn_id = int(callback.data.split(":")[-1])
    conn = await get_connection(session, conn_id, callback.from_user.id)
    if not conn:
        await callback.answer("Подключение не найдено.", show_alert=True)
        return
    await callback.message.edit_text(
        f"Отключить «{conn.name}»? Доступ прекратится сразу, деньги за оставшиеся дни не возвращаются.",
        reply_markup=_confirm_keyboard(f"menu:disable_do:{conn_id}", f"menu:connection:{conn_id}"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("menu:disable_do:"))
async def disable_do(callback: CallbackQuery, session: AsyncSession) -> None:
    conn_id = int(callback.data.split(":")[-1])
    conn = await get_connection(session, conn_id, callback.from_user.id)
    if not conn:
        await callback.answer("Подключение не найдено.", show_alert=True)
        return
    await deactivate(session, conn)
    await callback.answer("Отключено", show_alert=True)
    await callback.message.edit_text(_connection_card_text(conn), reply_markup=connection_card_keyboard(conn))


def _confirm_keyboard(yes_data: str, no_data: str):
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Да", callback_data=yes_data)
    kb.button(text="⬅️ Отмена", callback_data=no_data)
    kb.adjust(1)
    return kb.as_markup()


@router.callback_query(F.data == "menu:referral")
async def referral(callback: CallbackQuery, session: AsyncSession) -> None:
    me = await callback.bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{callback.from_user.id}"

    invited_count = await session.scalar(
        select(func.count()).select_from(User).where(User.referrer_id == callback.from_user.id)
    )
    paid_count = await session.scalar(
        select(func.count(func.distinct(Payment.user_id)))
        .select_from(Payment)
        .join(User, User.tg_id == Payment.user_id)
        .where(User.referrer_id == callback.from_user.id, Payment.status == "paid")
    )
    bonuses = await session.execute(
        select(ReferralBonus).where(ReferralBonus.referrer_id == callback.from_user.id)
    )
    bonuses = bonuses.scalars().all()
    total_days = sum(b.bonus_days for b in bonuses)
    total_amount = sum(b.bonus_amount for b in bonuses)

    text = (
        "🎁 Бонус за друга\n\n"
        f"Получайте {settings.REFERRAL_BONUS_PERCENT}% с каждой покупки приглашённого друга "
        f"+ {settings.REFERRAL_BONUS_DAYS} дня подписки на баланс — за каждую его оплату, не только за первую.\n\n"
        f"Ваша ссылка:\n{link}\n\n"
        f"Приглашено: {invited_count or 0}\n"
        f"Оплатили подписку: {paid_count or 0}\n"
        f"Заработано: {total_amount} руб." + (f", {total_days} дн." if total_days else "")
    )
    await callback.message.edit_text(text, reply_markup=back_to_menu())
    await callback.answer()
