from __future__ import annotations

import datetime as dt

from aiogram import Router, F
from aiogram.types import CallbackQuery

from bot.keyboards.admin import back_to_admin
from bot.services.awg_agent import AwgAgentError, awg_agent
from bot.services.marzban import marzban_client, marzban_client_nl

router = Router(name="admin_activity")

# How recently a peer/user must have handshaked/transferred data to count
# as "online now" — wg only updates handshake on actual traffic (keepalive
# counts), and Marzban's online_at is bumped on every proxied request, so
# 10 minutes is a reasonable "currently using the VPN" window without being
# so tight it misses someone mid-session with bursty traffic.
ONLINE_WINDOW_MINUTES = 10


async def _count_wg_online(protocol: str) -> tuple[int, int]:
    try:
        peers = await awg_agent.get_status(protocol)
    except AwgAgentError:
        return 0, 0
    now = dt.datetime.utcnow().timestamp()
    online = sum(
        1 for p in peers if p["latest_handshake"] and now - p["latest_handshake"] < ONLINE_WINDOW_MINUTES * 60
    )
    return online, len(peers)


async def _count_marzban_online(client) -> tuple[int, int]:
    try:
        users = await client.list_users()
    except Exception:
        return 0, 0
    now = dt.datetime.utcnow()
    online = 0
    for u in users:
        online_at = u.get("online_at")
        if not online_at:
            continue
        try:
            ts = dt.datetime.fromisoformat(online_at)
        except ValueError:
            continue
        if (now - ts).total_seconds() < ONLINE_WINDOW_MINUTES * 60:
            online += 1
    return online, len(users)


@router.callback_query(F.data == "admin:activity")
async def activity(callback: CallbackQuery) -> None:
    await callback.answer("Собираю данные...")
    amnezia_online, amnezia_total = await _count_wg_online("amnezia")
    wg_online, wg_total = await _count_wg_online("wireguard")
    de_online, de_total = await _count_marzban_online(marzban_client)
    nl_online, nl_total = await _count_marzban_online(marzban_client_nl)

    total_online = amnezia_online + wg_online + de_online + nl_online
    total_all = amnezia_total + wg_total + de_total + nl_total

    text = (
        f"📶 Активность (последние {ONLINE_WINDOW_MINUTES} мин)\n\n"
        f"Всего онлайн: {total_online} из {total_all} подключений\n\n"
        f"AmneziaWG: {amnezia_online}/{amnezia_total}\n"
        f"WireGuard: {wg_online}/{wg_total}\n"
        f"VLESS/SS (Германия): {de_online}/{de_total}\n"
        f"VLESS/SS (Нидерланды): {nl_online}/{nl_total}"
    )
    await callback.message.edit_text(text, reply_markup=back_to_admin())
