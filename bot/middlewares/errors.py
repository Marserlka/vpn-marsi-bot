from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery

logger = logging.getLogger("bot.errors")


class ErrorLoggingMiddleware(BaseMiddleware):
    """Catches any exception raised deeper in the handler chain (including
    Marzban/payment API failures) so a single bad update never crashes the bot,
    per TZ section 5 ("errors.log", "не должны ронять скрипт бота")."""

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
            if notify_target is not None:
                try:
                    await notify_target.answer(
                        "Произошла техническая ошибка. Мы уже знаем о ней. Попробуйте позже или обратитесь в поддержку."
                    )
                except Exception:
                    logger.exception("Failed to notify user about the error")
            return None
