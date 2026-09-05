from __future__ import annotations

from aiogram import Router
from aiogram.filters import Filter
from aiogram.types import TelegramObject

from bot.config import settings


class IsAdmin(Filter):
    async def __call__(self, obj: TelegramObject) -> bool:
        user = getattr(obj, "from_user", None)
        return bool(user and user.id in settings.admin_ids)


def build_admin_router() -> Router:
    from bot.handlers.admin import broadcast, force_sub, free_period, payments, promocodes, stats, users

    router = Router(name="admin")
    router.message.filter(IsAdmin())
    router.callback_query.filter(IsAdmin())

    router.include_router(stats.router)
    router.include_router(users.router)
    router.include_router(payments.router)
    router.include_router(promocodes.router)
    router.include_router(broadcast.router)
    router.include_router(force_sub.router)
    router.include_router(free_period.router)
    return router
