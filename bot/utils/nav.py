from __future__ import annotations

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup


async def render(callback: CallbackQuery, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
    """Like callback.message.edit_text(), but safe to call from a handler
    reachable directly off the /start welcome photo: Telegram's edit_text
    fails with "there is no text in the message to edit" on a photo message
    (it only has a caption, not text) — see the 2026-09-05 postmortem.
    Photo messages get deleted and replaced with a fresh text message;
    everything downstream from there is plain text again, so subsequent
    navigation can keep using edit_text directly.

    The delete() itself can fail too — Telegram only lets a bot delete its
    own message within 48 hours in a private chat, and the welcome photo
    can easily be older than that by the time someone clicks a button on
    it (found 2026-09-05: a real user's "Личный кабинет" did nothing at
    all, silently — delete() threw, and the exception got swallowed
    upstream without ever notifying them). Falls back to just sending the
    new message and leaving the stale photo in place.
    """
    if callback.message.photo:
        try:
            await callback.message.delete()
        except TelegramBadRequest:
            pass
        await callback.message.answer(text, reply_markup=reply_markup)
    else:
        await callback.message.edit_text(text, reply_markup=reply_markup)
