from __future__ import annotations

from aiogram import Router
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import User
from bot.keyboards.client import main_menu
from bot.services.referrals import register_referral

router = Router(name="start")

WELCOME_TEXT = (
    "Добро пожаловать в VPN MARSI!\n\n"
    "1 подписка = 1 устройство, 30 руб./месяц.\n"
    "Внимание: при одновременном включении на двух устройствах доступ автоматически блокируется."
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
            await register_referral(session, user, referrer_id)
        except ValueError:
            pass

    await message.answer(WELCOME_TEXT, reply_markup=main_menu())
