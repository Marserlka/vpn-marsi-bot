from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware, Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, TelegramObject
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import settings
from bot.services.settings import get_settings

logger = logging.getLogger("bot.force_subscribe")


def _prompt_keyboard(channel_url: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📢 Подписаться", url=channel_url)
    kb.button(text="✅ Я подписался", callback_data="force_sub:check")
    kb.adjust(1)
    return kb.as_markup()


class ForceSubscribeMiddleware(BaseMiddleware):
    """Blocks every bot interaction until the user joins the admin-configured
    channel (see bot/handlers/admin/force_sub.py). Admins always bypass this,
    so they can't lock themselves out while configuring it."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is None or user.id in settings.admin_ids:
            return await handler(event, data)

        session = data.get("session")
        if session is None:
            return await handler(event, data)

        row = await get_settings(session)
        if not row.force_sub_enabled or not row.force_sub_channel_id:
            return await handler(event, data)

        # Let the "Я подписался" recheck button itself through — its handler
        # does the membership check and either lets the user in or repeats
        # the prompt; blocking it here would make the button do nothing.
        if isinstance(event, CallbackQuery) and event.data == "force_sub:check":
            return await handler(event, data)

        bot: Bot = data["bot"]
        try:
            member = await bot.get_chat_member(row.force_sub_channel_id, user.id)
            is_subscribed = member.status not in ("left", "kicked")
        except TelegramBadRequest:
            logger.exception("force_sub: failed to check membership for %s", user.id)
            is_subscribed = True  # fail open — a misconfigured channel must not lock everyone out

        if is_subscribed:
            return await handler(event, data)

        text = (
            "Для использования бота подпишитесь на наш канал, "
            "затем нажмите «Я подписался»."
        )
        keyboard = _prompt_keyboard(row.force_sub_channel_url or "https://t.me")
        if isinstance(event, Message):
            await event.answer(text, reply_markup=keyboard)
        elif isinstance(event, CallbackQuery):
            await event.answer("Подпишитесь на канал, чтобы продолжить.", show_alert=True)
            if event.message:
                await event.message.answer(text, reply_markup=keyboard)
        return None
