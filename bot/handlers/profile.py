from __future__ import annotations

import datetime as dt
import random
import string

from aiogram import Router, F
from aiogram.types import BufferedInputFile, CallbackQuery
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.database.models import Connection, ReferralBonus, User
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
from bot.utils.emoji import pe
from bot.utils.nav import render

router = Router(name="profile")

MIN_CONNECTION_AGE = dt.timedelta(days=settings.MIN_CONNECTION_AGE_DAYS)

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
    "vless": "нажмите на ссылку выше, чтобы скопировать её, и добавьте в приложении («Добавить подписку по ссылке»)",
    "ss": "нажмите на ссылку выше, чтобы скопировать её, и добавьте в приложении («Добавить подписку по ссылке»)",
}
REGION_LABELS = {"de": "🇩🇪 Германия", "all": "🌍 Все регионы"}


def random_config_filename() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"GermanMarsi-{suffix}.conf"


def _status_line(conn: Connection) -> str:
    if conn.status == "active":
        return "Статус: ✅ Активно"
    return "Статус: ❌ Удалено"


def _connection_age_left(conn: Connection) -> dt.timedelta:
    age = dt.datetime.utcnow() - conn.created_at
    return MIN_CONNECTION_AGE - age


def _connection_card_text(conn: Connection) -> str:
    limit_note = (
        "⚠️ Ограничение: 1 подключение = 1 устройство."
        if conn.protocol in ("amnezia", "wireguard")
        else "ℹ️ Для этого протокола ограничение на 1 устройство сейчас не действует."
    )
    billing_note = ""
    if conn.status == "active" and conn.next_charge_at:
        billing_note = (
            f"\nСледующее списание: {conn.next_charge_at.strftime('%d.%m.%Y')} "
            f"({settings.PRICE_PER_DAY_RUB} руб./день)"
        )
    lock_left = _connection_age_left(conn)
    lock_note = (
        f"\n🔒 Удаление станет доступно через {lock_left.days + 1} дн."
        if conn.status == "active" and lock_left.total_seconds() > 0
        else ""
    )
    return (
        f"{pe('connections')} {conn.name}\n\n"
        f"{_status_line(conn)}\n"
        f"Протокол: {PROTOCOL_LABELS.get(conn.protocol, conn.protocol)}\n"
        f"Регион: {REGION_LABELS.get(conn.region, conn.region)}"
        f"{billing_note}{lock_note}\n\n"
        f"{limit_note}"
    )


@router.callback_query(F.data == "menu:profile")
async def profile(callback: CallbackQuery, session: AsyncSession) -> None:
    user = await session.get(User, callback.from_user.id)
    conns = await list_connections(session, callback.from_user.id)
    active_count = sum(1 for c in conns if c.status == "active")

    text = (
        f"{pe('cabinet')} Личный кабинет\n\n"
        f"Баланс: {user.balance} руб.\n"
        f"Активных подключений: {active_count}\n\n"
        f"⚠️ Каждое подключение — 1 устройство."
    )
    await render(callback, text, profile_keyboard())
    await callback.answer()


@router.callback_query(F.data == "menu:connections")
async def connections_list(callback: CallbackQuery, session: AsyncSession) -> None:
    conns = await list_connections(session, callback.from_user.id)
    header = f"{pe('connections')} Мои подключения"
    text = header if conns else f"{header}\n\nПока нет ни одного подключения."
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
    copy one line) — send those as plain copyable text instead. Either way,
    a QR code of the same content follows right after (2026-09-05, admin
    request) — no separate button/click needed, both AmneziaVPN and the
    official WireGuard app support importing by scanning it."""
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

    await _send_qr(bot, chat_id, conn)


async def _send_qr(bot, chat_id: int, conn: Connection) -> None:
    import io

    import qrcode

    img = qrcode.make(conn.awg_config)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    photo = BufferedInputFile(buf.getvalue(), filename=f"{conn.name}-qr.png")
    await bot.send_photo(chat_id, photo, caption=f"📱 QR-код «{conn.name}» — можно отсканировать вместо файла.")


@router.callback_query(F.data.startswith("menu:get_config:"))
async def get_config(callback: CallbackQuery, session: AsyncSession) -> None:
    conn_id = int(callback.data.split(":")[-1])
    conn = await get_connection(session, conn_id, callback.from_user.id)
    if not conn or not conn.awg_config or conn.status != "active":
        await callback.answer("Нет активного конфига.", show_alert=True)
        return

    await send_connection_config(callback.bot, callback.message.chat.id, conn)
    await callback.answer()


@router.callback_query(F.data.startswith("menu:vless_keys:"))
async def vless_keys(callback: CallbackQuery, session: AsyncSession) -> None:
    """Since 2026-09-05 «Получить конфиг» sends the Marzban subscription URL,
    not a raw vless://ss:// link (see subscriptions.py:_provision — needed
    for custom-routing JSON templates later). Some clients/advanced users
    still want the individual per-inbound keys behind that subscription —
    this fetches them straight from Marzban and shows them as copyable text."""
    conn_id = int(callback.data.split(":")[-1])
    conn = await get_connection(session, conn_id, callback.from_user.id)
    if not conn or conn.protocol not in MARZBAN_FAMILY or conn.status != "active" or not conn.awg_public_key:
        await callback.answer("Недоступно для этого подключения.", show_alert=True)
        return

    from bot.services.marzban import marzban_client

    user_data = await marzban_client.get_user(conn.awg_public_key)
    links = (user_data or {}).get("links") or []
    if not links:
        await callback.answer("Ключи не найдены.", show_alert=True)
        return

    import html as html_lib

    body = "\n\n".join(f"<code>{html_lib.escape(link)}</code>" for link in links)
    await callback.message.answer(f"🔑 Ключи «{conn.name}»:\n\n{body}", parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("menu:regen:"))
async def regen_confirm(callback: CallbackQuery, session: AsyncSession) -> None:
    conn_id = int(callback.data.split(":")[-1])
    conn = await get_connection(session, conn_id, callback.from_user.id)
    if not conn:
        await callback.answer("Подключение не найдено.", show_alert=True)
        return
    await callback.message.edit_text(
        f"{pe('update_config')} Обновить конфиг «{conn.name}»?\n\n"
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
        f"{pe('switch_protocol')} Сменить протокол для «{conn.name}»:", reply_markup=protocol_switch_keyboard(conn)
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
    lock_left = _connection_age_left(conn)
    if lock_left.total_seconds() > 0:
        await callback.answer(
            f"Удалить можно не раньше чем через {settings.MIN_CONNECTION_AGE_DAYS} дней после создания "
            f"(осталось ещё {lock_left.days + 1} дн.).",
            show_alert=True,
        )
        return
    await callback.message.edit_text(
        f"{pe('delete')} Удалить «{conn.name}»? Доступ прекратится сразу, деньги за оставшиеся дни не возвращаются.",
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
    if _connection_age_left(conn).total_seconds() > 0:
        await callback.answer(
            f"Удалить можно не раньше чем через {settings.MIN_CONNECTION_AGE_DAYS} дней после создания.",
            show_alert=True,
        )
        return
    await deactivate(session, conn)
    await callback.answer("Удалено", show_alert=True)
    await callback.message.edit_text(_connection_card_text(conn), reply_markup=connection_card_keyboard(conn))


def _confirm_keyboard(yes_data: str, no_data: str):
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from bot.utils.emoji import PE_ID

    kb = InlineKeyboardBuilder()
    kb.button(text="Да", callback_data=yes_data, icon_custom_emoji_id=PE_ID["active"])
    kb.button(text="Отмена", callback_data=no_data, icon_custom_emoji_id=PE_ID["back"])
    kb.adjust(1)
    return kb.as_markup()


@router.callback_query(F.data == "menu:referral")
async def referral(callback: CallbackQuery, session: AsyncSession) -> None:
    me = await callback.bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{callback.from_user.id}"

    invited_count = await session.scalar(
        select(func.count()).select_from(User).where(User.referrer_id == callback.from_user.id)
    )
    bonuses = (
        await session.execute(select(ReferralBonus).where(ReferralBonus.referrer_id == callback.from_user.id))
    ).scalars().all()
    total_amount = sum(b.bonus_amount for b in bonuses)

    text = (
        f"{pe('invite')} Бонус за друга\n\n"
        f"Приглашайте друзей — получайте {settings.REFERRAL_BONUS_RUB} руб. на баланс, как только "
        "приглашённый впервые пополнит свой баланс (один раз за каждого друга).\n\n"
        f"Ваша ссылка:\n{link}\n\n"
        f"Приглашено: {invited_count or 0}\n"
        f"Пополнили баланс: {len(bonuses)}\n"
        f"Заработано всего: {total_amount} руб."
    )
    await render(callback, text, back_to_menu())
    await callback.answer()
