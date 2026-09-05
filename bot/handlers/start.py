from __future__ import annotations

import datetime as dt
from pathlib import Path

from aiogram import Router, F, Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import CallbackQuery, FSInputFile, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.database.models import BalanceTransaction, User
from bot.keyboards.client import captcha_keyboard, main_menu
from bot.services.referrals import register_referral
from bot.services.settings import get_settings
from bot.utils.emoji import pe

router = Router(name="start")

WELCOME_IMAGE = Path(__file__).resolve().parent.parent / "assets" / "welcome.jpg"


def welcome_text() -> str:
    """A function, not a module-level constant, so the price can never go
    stale again the way the old hardcoded "30 руб./месяц" did after tariffs
    changed to 50/100/150 — always reads the current live rate (per-day
    billing since 2026-09-05, see TZ)."""
    return (
        "Добро пожаловать в Marsi VPN!\n\n"
        f"Стоимость — {settings.PRICE_PER_DAY_RUB}{pe('price')}/день за подключение."
    )

CAPTCHA_TEXT = (
    "Добро пожаловать в VPN MARSI!\n\n"
    "Вас пригласил друг. Подтвердите, что вы не бот, чтобы продолжить — "
    f"у вас есть {settings.REFERRAL_CAPTCHA_TIMEOUT_SECONDS} секунд."
)


async def get_or_create_user(session: AsyncSession, tg_id: int, username: str | None) -> tuple[User, bool]:
    """Shared by cmd_start and check_force_sub — a user who hits the
    force-subscribe gate on their very first /start never reaches cmd_start
    at all (the middleware blocks it before the handler runs), so without
    this, check_force_sub would show the main menu for someone who has no
    User row yet at all, and the first button they press (e.g. «Личный
    кабинет») would crash on a None user (found 2026-09-05)."""
    user = await session.get(User, tg_id)
    is_new = user is None
    if user is None:
        user = User(tg_id=tg_id, username=username, balance=settings.WELCOME_BONUS_RUB)
        session.add(user)
        await session.flush()
        session.add(BalanceTransaction(user_id=user.tg_id, delta=settings.WELCOME_BONUS_RUB, reason="welcome_bonus"))
    elif user.username != username:
        user.username = username
    return user, is_new


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, session: AsyncSession) -> None:
    user, is_new = await get_or_create_user(session, message.from_user.id, message.from_user.username)

    if is_new and command.args and command.args.startswith("ref_"):
        try:
            referrer_id = int(command.args.removeprefix("ref_"))
        except ValueError:
            referrer_id = None
        if referrer_id is not None and referrer_id != user.tg_id:
            await message.answer(CAPTCHA_TEXT, reply_markup=captcha_keyboard(referrer_id))
            return

    row = await get_settings(session)
    caption = welcome_text()
    if is_new:
        caption += f"\n\n🎁 Дарим {settings.WELCOME_BONUS_RUB} руб. на баланс за регистрацию!"
    await message.answer_photo(
        FSInputFile(WELCOME_IMAGE),
        caption=caption,
        reply_markup=main_menu(row.force_sub_channel_url),
    )


@router.callback_query(F.data.startswith("start:verify:"))
async def verify_captcha(callback: CallbackQuery, session: AsyncSession) -> None:
    referrer_id = int(callback.data.split(":")[-1])

    age = dt.datetime.utcnow() - callback.message.date.replace(tzinfo=None)
    if age.total_seconds() > settings.REFERRAL_CAPTCHA_TIMEOUT_SECONDS:
        await callback.answer("Время вышло, начните заново командой /start.", show_alert=True)
        return

    user = await session.get(User, callback.from_user.id)
    if user is not None:
        await register_referral(session, user, referrer_id)

    row = await get_settings(session)
    await callback.message.edit_text(welcome_text(), reply_markup=main_menu(row.force_sub_channel_url))
    await callback.answer("Спасибо!")


@router.callback_query(F.data == "force_sub:check")
async def check_force_sub(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    row = await get_settings(session)
    if not row.force_sub_enabled or not row.force_sub_channel_id:
        await get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        await _finish_force_sub(callback, row)
        return

    try:
        member = await bot.get_chat_member(row.force_sub_channel_id, callback.from_user.id)
        is_subscribed = member.status not in ("left", "kicked")
    except TelegramBadRequest:
        is_subscribed = True

    if not is_subscribed:
        await callback.answer("Не вижу вашей подписки. Подпишитесь и попробуйте снова.", show_alert=True)
        return

    await get_or_create_user(session, callback.from_user.id, callback.from_user.username)
    await _finish_force_sub(callback, row)


async def _finish_force_sub(callback: CallbackQuery, row) -> None:
    """Edits the existing prompt in place instead of posting a fresh welcome
    message every time — a repeat tap on «Я подписался» (double-click, or a
    retry after the alert) used to spam a brand-new message each time since
    this used to call .answer() unconditionally (found 2026-09-05)."""
    try:
        await callback.message.edit_text(welcome_text(), reply_markup=main_menu(row.force_sub_channel_url))
    except TelegramBadRequest:
        pass  # already showing this exact text/markup — nothing to change
    await callback.answer("Спасибо! Доступ открыт.")
