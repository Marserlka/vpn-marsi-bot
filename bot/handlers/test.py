from __future__ import annotations

import uuid

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from bot.handlers.admin import IsAdmin
from bot.services.cdn_check import check_cdn_readiness
from bot.services.testlab import get_cdn_config, get_olcrtc_config, set_cdn_config, set_olcrtc_config

router = Router(name="test_lab")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

# Everything here is scratch space for evaluating whitelist-bypass ideas
# (currently: OlcRTC, tunneling a SOCKS5 proxy through a Yandex Telemost
# WebRTC DataChannel — see TZ discussion 2026-09-05) before any of it is
# considered for the real client-facing protocols. Admin-only, deliberately
# kept out of bot/handlers/admin/* and the client keyboards entirely so it
# can't accidentally reach a paying user.

OLCRTC_INSTALL_TEXT = (
    "<b>Сервер (VPS):</b>\n"
    "<code>sudo -v\n"
    "bash &lt;(curl -sL zarazaex.xyz/srv.sh)</code>\n"
    "Вводите ID конференции (создать заранее в Яндекс.Телемосте) — получаете ключ шифрования.\n\n"
    "<b>Клиент:</b>\n"
    "<code>sudo -v\n"
    "bash &lt;(curl -sL zarazaex.xyz/cnc.sh)</code>\n"
    "Вводите ID, ключ, порт (по умолчанию 8809) — получаете локальный SOCKS5h прокси.\n\n"
    "<b>Проверка:</b>\n"
    "<code>all_proxy=socks5h://localhost:8809 curl -fsSL zarazaex.xyz</code>\n\n"
    "⚠️ Экспериментально: только Linux, нет мимикрии трафика, зависит от бага 8KB-лимита "
    "в Телемосте — Яндекс может это в любой момент починить/забанить."
)


CDN_SETUP_TEXT = (
    "1. Купить домен (любой регистратор, лучше не .ru).\n"
    "2. Добавить домен в Cloudflare, прописать у регистратора NS-сервера, которые покажет CF.\n"
    "3. В CF создать A-запись на поддомен (например vpn.домен.com) → IP VPS, статус <b>Proxied</b> "
    "(оранжевое облако).\n"
    "4. SSL/TLS → режим <b>Full (strict)</b>.\n"
    "5. My Profile → API Tokens → Create Token → Edit zone DNS (права только на этот домен) — "
    "сюда сохранить сам токен и Zone ID со страницы обзора домена.\n\n"
    "Когда DNS применится — проверка ниже покажет, что домен реально идёт через Cloudflare, "
    "и можно будет ставить Xray-инбаунд (VLESS+WS+TLS) на VPS под этот домен."
)


class OlcRtcStates(StatesGroup):
    waiting_config = State()


class CdnStates(StatesGroup):
    waiting_config = State()


def _lab_main_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="📡 OlcRTC (обход БС через Телемост)", callback_data="test:olcrtc")
    kb.button(text="☁️ CDN-фронтинг (Cloudflare + VLESS)", callback_data="test:cdn")
    kb.adjust(1)
    return kb.as_markup()


def _cdn_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="📖 Что нужно сделать", callback_data="test:cdn:howto")
    kb.button(text="✏️ Задать домен/токен", callback_data="test:cdn:set")
    kb.button(text="🔍 Проверить DNS/Cloudflare", callback_data="test:cdn:check")
    kb.button(text="⬅️ Назад", callback_data="test:main")
    kb.adjust(1)
    return kb.as_markup()


def _olcrtc_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="📖 Инструкция по установке", callback_data="test:olcrtc:howto")
    kb.button(text="✏️ Задать конфигурацию", callback_data="test:olcrtc:set")
    kb.button(text="⬅️ Назад", callback_data="test:main")
    kb.adjust(1)
    return kb.as_markup()


@router.message(Command("test"))
async def test_entry(message: Message) -> None:
    await message.answer("🧪 Тестовая лаборатория (только админ)", reply_markup=_lab_main_keyboard())


@router.callback_query(F.data == "test:main")
async def test_main(callback: CallbackQuery) -> None:
    await callback.message.edit_text("🧪 Тестовая лаборатория (только админ)", reply_markup=_lab_main_keyboard())
    await callback.answer()


@router.callback_query(F.data == "test:olcrtc")
async def olcrtc_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    cfg = await get_olcrtc_config(session)
    if cfg.conference_id:
        status = (
            f"Конференция: <code>{cfg.conference_id}</code>\n"
            f"Ключ: <code>{cfg.encryption_key or '—'}</code>\n"
            f"SOCKS5 порт: {cfg.socks5_port or 8809}"
        )
        if cfg.notes:
            status += f"\nЗаметки: {cfg.notes}"
    else:
        status = "Пока не настроено — создайте конференцию в Телемосте вручную и сохраните данные сюда."

    await callback.message.edit_text(
        f"📡 OlcRTC — обход белых списков через Yandex Telemost\n\n{status}",
        reply_markup=_olcrtc_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "test:olcrtc:howto")
async def olcrtc_howto(callback: CallbackQuery) -> None:
    await callback.message.answer(OLCRTC_INSTALL_TEXT)
    await callback.answer()


@router.callback_query(F.data == "test:olcrtc:set")
async def olcrtc_set_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(OlcRtcStates.waiting_config)
    await callback.message.edit_text(
        "Отправьте одним сообщением через пробел: <code>ID_конференции ключ порт</code>\n"
        "(порт можно не указывать — по умолчанию 8809)",
    )
    await callback.answer()


@router.message(OlcRtcStates.waiting_config)
async def olcrtc_set_done(message: Message, state: FSMContext, session: AsyncSession) -> None:
    parts = message.text.strip().split()
    if len(parts) < 2:
        await message.answer("Нужно минимум ID конференции и ключ, через пробел. Введите ещё раз:")
        return

    conference_id, key = parts[0], parts[1]
    port = None
    if len(parts) >= 3:
        try:
            port = int(parts[2])
        except ValueError:
            await message.answer("Порт должен быть числом. Введите ещё раз:")
            return

    await set_olcrtc_config(session, conference_id=conference_id, encryption_key=key, socks5_port=port)
    await state.clear()
    await message.answer("Сохранено.", reply_markup=_olcrtc_keyboard())


@router.callback_query(F.data == "test:cdn")
async def cdn_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    cfg = await get_cdn_config(session)
    if cfg.domain:
        status = (
            f"Домен: <code>{cfg.domain}</code>\n"
            f"Zone ID: <code>{cfg.cf_zone_id or '—'}</code>\n"
            f"CF-токен: {'задан' if cfg.cf_api_token else '—'}\n"
            f"VLESS UUID: <code>{cfg.vless_uuid or '—'}</code>\n"
            f"WS path: <code>{cfg.ws_path or '/vless'}</code>"
        )
    else:
        status = "Пока не настроено."

    await callback.message.edit_text(
        f"☁️ CDN-фронтинг — VLESS за Cloudflare\n\n{status}",
        reply_markup=_cdn_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "test:cdn:howto")
async def cdn_howto(callback: CallbackQuery) -> None:
    await callback.message.answer(CDN_SETUP_TEXT)
    await callback.answer()


@router.callback_query(F.data == "test:cdn:set")
async def cdn_set_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(CdnStates.waiting_config)
    await callback.message.edit_text(
        "Отправьте одним сообщением через пробел: <code>домен zone_id cf_токен</code>\n"
        "Например: <code>vpn.example.com a1b2c3... 0xAbCdEf...</code>\n\n"
        "UUID для VLESS-клиента сгенерируется автоматически.",
    )
    await callback.answer()


@router.message(CdnStates.waiting_config)
async def cdn_set_done(message: Message, state: FSMContext, session: AsyncSession) -> None:
    parts = message.text.strip().split()
    if len(parts) < 3:
        await message.answer("Нужны домен, zone_id и токен, через пробел. Введите ещё раз:")
        return

    domain, zone_id, token = parts[0], parts[1], parts[2]
    cfg = await get_cdn_config(session)
    vless_uuid = cfg.vless_uuid or str(uuid.uuid4())

    await set_cdn_config(
        session,
        domain=domain,
        cf_zone_id=zone_id,
        cf_api_token=token,
        vless_uuid=vless_uuid,
        ws_path=cfg.ws_path or "/vless",
    )
    await state.clear()
    await message.answer(f"Сохранено. VLESS UUID: <code>{vless_uuid}</code>", reply_markup=_cdn_keyboard())


@router.callback_query(F.data == "test:cdn:check")
async def cdn_check(callback: CallbackQuery, session: AsyncSession) -> None:
    cfg = await get_cdn_config(session)
    if not cfg.domain:
        await callback.answer("Сначала задай домен.", show_alert=True)
        return

    await callback.answer("Проверяю...")
    result = await check_cdn_readiness(cfg.domain)
    await callback.message.answer(f"🔍 {cfg.domain}\n\n{result}")
