from __future__ import annotations

from aiogram import Router, F
from aiogram.types import CallbackQuery

from bot.config import settings
from bot.handlers.start import WELCOME_TEXT
from bot.keyboards.client import back_to_menu, main_menu

router = Router(name="menu")


@router.callback_query(F.data == "menu:main")
async def to_main_menu(callback: CallbackQuery) -> None:
    await callback.message.edit_text(WELCOME_TEXT, reply_markup=main_menu())
    await callback.answer()


@router.callback_query(F.data == "menu:instructions")
async def instructions(callback: CallbackQuery) -> None:
    text = (
        "📥 Инструкция по подключению\n\n"
        "1. Установите приложение AmneziaVPN (iOS / Android / Windows / macOS).\n"
        "2. Зайдите в «Личный кабинет» → «Получить конфиг» — бот пришлёт файл .conf.\n"
        "3. В приложении: «Добавить конфигурацию» → «Импортировать из файла» → выберите присланный файл.\n"
        "4. Нажмите «Подключиться».\n\n"
        "Если что-то не работает — обратитесь в поддержку."
    )
    await callback.message.edit_text(text, reply_markup=back_to_menu())
    await callback.answer()


@router.callback_query(F.data == "menu:support")
async def support(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        f"🆘 Поддержка: напишите администратору — @{settings.SUPPORT_USERNAME}",
        reply_markup=back_to_menu(),
    )
    await callback.answer()
