from __future__ import annotations

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.admin import back_to_admin, force_sub_keyboard
from bot.services.settings import get_settings

router = Router(name="admin_force_sub")


class ForceSubStates(StatesGroup):
    waiting_channel = State()


def _status_text(row) -> str:
    state = "включена ✅" if row.force_sub_enabled else "выключена ❌"
    channel = row.force_sub_channel_id or "не задан"
    return (
        "🔒 Обязательная подписка на канал\n\n"
        f"Статус: {state}\n"
        f"Канал (chat_id): {channel}\n"
        f"Ссылка: {row.force_sub_channel_url or '—'}"
    )


@router.callback_query(F.data == "admin:force_sub")
async def force_sub_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    row = await get_settings(session)
    await callback.message.edit_text(_status_text(row), reply_markup=force_sub_keyboard(row.force_sub_enabled))
    await callback.answer()


@router.callback_query(F.data == "admin:force_sub:enable")
async def enable_force_sub(callback: CallbackQuery, session: AsyncSession) -> None:
    row = await get_settings(session)
    if not row.force_sub_channel_id:
        await callback.answer("Сначала задайте канал.", show_alert=True)
        return
    row.force_sub_enabled = True
    await session.flush()
    await callback.message.edit_text(_status_text(row), reply_markup=force_sub_keyboard(True))
    await callback.answer("Включено")


@router.callback_query(F.data == "admin:force_sub:disable")
async def disable_force_sub(callback: CallbackQuery, session: AsyncSession) -> None:
    row = await get_settings(session)
    row.force_sub_enabled = False
    await session.flush()
    await callback.message.edit_text(_status_text(row), reply_markup=force_sub_keyboard(False))
    await callback.answer("Отключено")


@router.callback_query(F.data == "admin:force_sub:set")
async def ask_channel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ForceSubStates.waiting_channel)
    await callback.message.edit_text(
        "Отправьте одним сообщением: `chat_id ссылка`\n\n"
        "Пример: `-1001234567890 https://t.me/+hVEJE2F6xUdmMTRi`\n\n"
        "chat_id канала узнайте так: сделайте бота админом канала, перешлите любое "
        "сообщение из канала боту @getidsbot — он покажет chat_id вида -100xxxxxxxxxx.",
        reply_markup=back_to_admin(),
        parse_mode="Markdown",
    )
    await callback.answer()


@router.message(ForceSubStates.waiting_channel)
async def channel_entered(message: Message, state: FSMContext, session: AsyncSession) -> None:
    parts = message.text.strip().split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("Формат: `chat_id ссылка`. Попробуйте ещё раз.", parse_mode="Markdown")
        return
    try:
        chat_id = int(parts[0])
    except ValueError:
        await message.answer("chat_id должен быть числом (например -1001234567890).")
        return

    row = await get_settings(session)
    row.force_sub_channel_id = chat_id
    row.force_sub_channel_url = parts[1]
    await session.flush()
    await state.clear()

    await message.answer(_status_text(row), reply_markup=force_sub_keyboard(row.force_sub_enabled))
