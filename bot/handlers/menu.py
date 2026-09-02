from __future__ import annotations

from aiogram import Router, F
from aiogram.types import CallbackQuery

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
        "1. Скачайте приложение: Amnezia VPN, FoXray (iOS), v2rayNG (Android) или NekoBox (ПК).\n"
        "2. Скопируйте вашу ссылку из раздела «Личный кабинет».\n"
        "3. В приложении выберите «Добавить конфигурацию по ссылке / подписке» и вставьте её.\n"
        "4. Нажмите «Подключиться».\n\n"
        "Если что-то не работает — обратитесь в поддержку."
    )
    await callback.message.edit_text(text, reply_markup=back_to_menu())
    await callback.answer()


@router.callback_query(F.data == "menu:support")
async def support(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "🆘 Поддержка: напишите администратору — @your_support_username",
        reply_markup=back_to_menu(),
    )
    await callback.answer()
