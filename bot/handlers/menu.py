from __future__ import annotations

from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.handlers.start import welcome_text
from bot.keyboards.client import back_to_menu, legal_docs_keyboard, main_menu
from bot.services.settings import get_settings
from bot.utils.emoji import pe
from bot.utils.nav import render

router = Router(name="menu")


@router.callback_query(F.data == "menu:main")
async def to_main_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    row = await get_settings(session)
    await render(callback, welcome_text(), main_menu(row.force_sub_channel_url))
    await callback.answer()


@router.callback_query(F.data == "menu:instructions")
async def instructions(callback: CallbackQuery) -> None:
    text = (
        f"{pe('instructions')} Инструкция по подключению\n\n"
        "1. Установите приложение под ваш протокол (AmneziaVPN, WireGuard и т.п.).\n"
        "2. «📡 Мои подключения» → выберите подключение → «Получить конфиг» — бот пришлёт файл.\n"
        "3. В приложении: «Добавить конфигурацию» → «Импортировать из файла» → выберите присланный файл.\n"
        "4. Нажмите «Подключиться».\n\n"
        "Если что-то не работает — обратитесь в поддержку."
    )
    await render(callback, text, back_to_menu())
    await callback.answer()


@router.callback_query(F.data == "menu:legal")
async def legal(callback: CallbackQuery) -> None:
    await render(callback, f"{pe('legal')} Правовые документы сервиса:", legal_docs_keyboard())
    await callback.answer()


@router.callback_query(F.data == "menu:support")
async def support(callback: CallbackQuery) -> None:
    await render(
        callback,
        f"{pe('support')} Поддержка: напишите администратору — @{settings.SUPPORT_USERNAME}",
        back_to_menu(),
    )
    await callback.answer()
