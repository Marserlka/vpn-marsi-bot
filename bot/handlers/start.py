from __future__ import annotations

import datetime as dt
from pathlib import Path

from aiogram import Router, F, Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import CallbackQuery, FSInputFile, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.database.models import User
from bot.keyboards.client import captcha_keyboard, main_menu
from bot.services.referrals import register_referral
from bot.services.settings import get_settings

router = Router(name="start")

WELCOME_IMAGE = Path(__file__).resolve().parent.parent / "assets" / "welcome.jpg"

WELCOME_TEXT = (
    "Добро пожаловать в VPN MARSI!\n\n"
    "1 подписка = 1 устройство, 30 руб./месяц.\n"
    "Внимание: при одновременном включении на двух устройствах доступ автоматически блокируется."
)

CAPTCHA_TEXT = (
    "Добро пожаловать в VPN MARSI!\n\n"
    "Вас пригласил друг. Подтвердите, что вы не бот, чтобы продолжить — "
    f"у вас есть {settings.REFERRAL_CAPTCHA_TIMEOUT_SECONDS} секунд."
)


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, session: AsyncSession) -> None:
    user = await session.get(User, message.from_user.id)
    is_new = user is None
    if user is None:
        user = User(tg_id=message.from_user.id, username=message.from_user.username)
        session.add(user)
        await session.flush()
    elif user.username != message.from_user.username:
        user.username = message.from_user.username

    if is_new and command.args and command.args.startswith("ref_"):
        try:
            referrer_id = int(command.args.removeprefix("ref_"))
        except ValueError:
            referrer_id = None
        if referrer_id is not None and referrer_id != user.tg_id:
            await message.answer(CAPTCHA_TEXT, reply_markup=captcha_keyboard(referrer_id))
            return

    row = await get_settings(session)
    await message.answer_photo(
        FSInputFile(WELCOME_IMAGE),
        caption=WELCOME_TEXT,
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
    await callback.message.edit_text(WELCOME_TEXT, reply_markup=main_menu(row.force_sub_channel_url))
    await callback.answer("Спасибо!")


@router.callback_query(F.data == "force_sub:check")
async def check_force_sub(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    row = await get_settings(session)
    if not row.force_sub_enabled or not row.force_sub_channel_id:
        await callback.message.answer(WELCOME_TEXT, reply_markup=main_menu(row.force_sub_channel_url))
        await callback.answer()
        return

    try:
        member = await bot.get_chat_member(row.force_sub_channel_id, callback.from_user.id)
        is_subscribed = member.status not in ("left", "kicked")
    except TelegramBadRequest:
        is_subscribed = True

    if not is_subscribed:
        await callback.answer("Не вижу вашей подписки. Подпишитесь и попробуйте снова.", show_alert=True)
        return

    await callback.message.answer(WELCOME_TEXT, reply_markup=main_menu(row.force_sub_channel_url))
    await callback.answer("Спасибо! Доступ открыт.")
