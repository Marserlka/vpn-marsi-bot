from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def do_ikb(
    data1: list[str],
    data2: list[str],
    layout: list[int],
    color: str | None = None,
    icons: dict[int, str] | None = None,
) -> InlineKeyboardMarkup:
    """Builds an inline keyboard from parallel lists of button texts (data1)
    and callback_data (data2), arranged into rows per `layout` (row sizes,
    must sum to len(data1)).

    `icons` maps a button's position in data1/data2 to a premium custom
    emoji id (see bot/utils/emoji.py PE_ID) shown next to its text —
    requires aiogram >=3.25.0. `color` applies a Bot API button style
    ("primary"/"success"/"danger") to every button in this call.
    """
    builder = InlineKeyboardBuilder()
    for idx, (text, callback_data) in enumerate(zip(data1, data2)):
        kwargs: dict = {}
        if color:
            kwargs["style"] = color
        if icons and idx in icons:
            kwargs["icon_custom_emoji_id"] = icons[idx]
        builder.button(text=text, callback_data=callback_data, **kwargs)
    builder.adjust(*layout)
    return builder.as_markup()
