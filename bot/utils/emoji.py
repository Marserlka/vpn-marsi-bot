"""Premium (custom) emoji support.

Telegram Premium custom emoji can only be rendered two ways:
  1. In message text via the `<tg-emoji emoji-id="...">fallback</tg-emoji>`
     HTML tag (parse_mode="HTML") — see pe() below.
  2. On an InlineKeyboardButton via its `icon_custom_emoji_id` field
     (aiogram >=3.25.0 / Bot API 9.4+ only — older versions don't have
     this field at all, see do_ikb() in bot/keyboards/_helpers.py).

Both need a real custom_emoji_id, which is Telegram-Premium-specific and
can't be derived from a unicode emoji — it has to be looked up by sending
the emoji to a bot like @RawDataBot / @ShowJsonBot and reading the
`custom_emoji_id` field off the resulting message entity.

Every entry here also carries a plain-unicode _FALLBACK: viewers without
Telegram Premium (and inline-mode / channel-post contexts, where custom
emoji aren't supported at all per the tg-emoji docs) see the fallback
character instead, never a broken/missing icon.
"""
from __future__ import annotations

PE_ID: dict[str, str] = {
    "cabinet": "5420484229198812151",
    "invite": "5260679323727204402",
    "support": "5370802328146318647",
    "news": "5328194414323980905",
    "legal": "5368454557288391017",
    "instructions": "5456127028916961325",
    "connections": "5879585266426973039",
    "add_connection": "5260606811794351458",
    "price": "5377746319601324795",
    "get_config": "5899757765743615694",
    "update_config": "5845943483382110702",
    "switch_protocol": "5843826335088120045",
    "delete": "5985493993100679671",
    # Same real checkmark id as "news" (5328194414323980905) — reused here
    # for a different semantic (connection status), not a duplicate mistake.
    "active": "5328194414323980905",
    "inactive": "5330500738747487365",
    "back": "5875082500023258804",
}

_FALLBACK: dict[str, str] = {
    "cabinet": "✈️",
    "invite": "💙",
    "support": "💙",
    "news": "✅",
    "legal": "⚠️",
    "instructions": "💙",
    "connections": "🌐",
    "add_connection": "💙",
    "price": "💰",
    "get_config": "⬇️",
    "update_config": "🔄",
    "switch_protocol": "💬",
    "delete": "🗑",
    "active": "✅",
    "inactive": "❌",
    "back": "⬅️",
}


def pe(name: str) -> str:
    """Returns a `<tg-emoji>` tag for use in HTML-parsed message text.
    Falls back to a plain unicode emoji if `name` isn't registered."""
    emoji_id = PE_ID.get(name)
    fallback = _FALLBACK.get(name, "⭐")
    if not emoji_id:
        return fallback
    return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'
