from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery, Update

logger = logging.getLogger("bot.errors")


class ErrorLoggingMiddleware(BaseMiddleware):
    """Catches any exception raised deeper in the handler chain (including
    Marzban/payment API failures) so a single bad update never crashes the bot,
    per TZ section 5 ("errors.log", "не должны ронять скрипт бота").

    Registered on dp.update.middleware() deliberately (not dp.message/
    dp.callback_query) so it wraps DbSessionMiddleware too — an exception
    needs to propagate out through the session's `async with` block for the
    transaction to actually roll back before this catches it; catching it
    any further in would let DbSessionMiddleware commit a half-written
    transaction. The cost is that `event` here is the raw Update, not a
    Message/CallbackQuery — it has to unwrap that itself to find something
    to reply to (found 2026-09-05 missing this exact unwrap: real handler
    exceptions were being caught and logged fine, but the "technical error"
    notice never reached the user because isinstance(event, Message) was
    never true for a bare Update — a button just silently did nothing).
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        try:
            return await handler(event, data)
        except Exception:
            logger.exception("Unhandled error while processing update: %s", event)
            notify_target = None
            if isinstance(event, Message):
                notify_target = event
            elif isinstance(event, CallbackQuery) and event.message:
                notify_target = event.message
            elif isinstance(event, Update):
                if event.message:
                    notify_target = event.message
                elif event.callback_query and event.callback_query.message:
                    notify_target = event.callback_query.message
            if notify_target is not None:
                try:
                    await notify_target.answer(
                        "Произошла техническая ошибка. Мы уже знаем о ней. Попробуйте позже или обратитесь в поддержку."
                    )
                except Exception:
                    logger.exception("Failed to notify user about the error")
            return None
