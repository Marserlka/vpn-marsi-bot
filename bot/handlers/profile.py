from __future__ import annotations

from aiogram import Router, F
from aiogram.types import BufferedInputFile, CallbackQuery
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.database.models import Payment, ReferralBonus, Subscription, User
from bot.keyboards.client import back_to_menu, manage_keyboard, profile_keyboard
from bot.services.subscriptions import get_or_create_subscription, switch_protocol

router = Router(name="profile")

PROTOCOL_LABELS = {"amnezia": "AmneziaWG (маскировка)", "wireguard": "WireGuard (скорость)"}
PROTOCOL_APP = {
    "amnezia": "приложение AmneziaVPN",
    "wireguard": "официальное приложение WireGuard",
}


def _status_line(sub: Subscription) -> str:
    if sub.status == "active" and sub.expires_at:
        return f"Статус: ✅ Активна до {sub.expires_at.strftime('%d.%m.%Y')}"
    return "Статус: ❌ Истекла"


@router.callback_query(F.data == "menu:profile")
async def profile(callback: CallbackQuery, session: AsyncSession) -> None:
    user = await session.get(User, callback.from_user.id)
    sub = await get_or_create_subscription(session, callback.from_user.id)

    text = (
        f"🌐 Личный кабинет\n\n"
        f"{_status_line(sub)}\n"
        f"Баланс: {user.balance} руб.\n\n"
        f"⚠️ 1 подписка предназначена только для 1 устройства."
    )
    await callback.message.edit_text(text, reply_markup=profile_keyboard())
    await callback.answer()


@router.callback_query(F.data == "menu:manage")
async def manage(callback: CallbackQuery, session: AsyncSession) -> None:
    sub = await get_or_create_subscription(session, callback.from_user.id)

    text = (
        f"⚙️ Управление подключениями\n\n"
        f"{_status_line(sub)}\n"
        f"Протокол: {PROTOCOL_LABELS.get(sub.protocol, sub.protocol)}\n\n"
        f"⚠️ 1 подписка предназначена только для 1 устройства. При одновременном "
        f"включении на двух устройствах доступ автоматически блокируется."
    )
    await callback.message.edit_text(
        text,
        reply_markup=manage_keyboard(
            has_config=bool(sub.awg_config), is_active=sub.status == "active", protocol=sub.protocol
        ),
    )
    await callback.answer()


@router.callback_query(F.data == "menu:get_config")
async def get_config(callback: CallbackQuery, session: AsyncSession) -> None:
    sub = await session.scalar(select(Subscription).where(Subscription.user_id == callback.from_user.id))
    if not sub or not sub.awg_config or sub.status != "active":
        await callback.answer("У вас нет активной подписки.", show_alert=True)
        return

    app_name = PROTOCOL_APP.get(sub.protocol, "приложение AmneziaVPN")
    file = BufferedInputFile(sub.awg_config.encode(), filename="vpnmarsi.conf")
    await callback.message.answer_document(
        file,
        caption=(
            f"Ваш конфиг ({PROTOCOL_LABELS.get(sub.protocol, sub.protocol)}).\n\n"
            f"1. Установите {app_name}.\n"
            "2. «Добавить конфигурацию» → «Импортировать из файла» → выберите этот файл.\n"
            "3. Подключитесь.\n\n"
            "⚠️ 1 подписка = 1 устройство."
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("menu:switch_protocol:"))
async def switch_protocol_handler(callback: CallbackQuery, session: AsyncSession) -> None:
    new_protocol = callback.data.split(":")[-1]
    try:
        sub = await switch_protocol(session, callback.from_user.id, new_protocol)
    except ValueError:
        await callback.answer("Нет активной подписки.", show_alert=True)
        return
    except Exception as exc:
        await callback.answer(f"Ошибка: {exc}", show_alert=True)
        raise

    await callback.answer(f"Протокол изменён на {PROTOCOL_LABELS.get(new_protocol, new_protocol)}", show_alert=True)
    text = (
        f"⚙️ Управление подключениями\n\n"
        f"{_status_line(sub)}\n"
        f"Протокол: {PROTOCOL_LABELS.get(sub.protocol, sub.protocol)}\n\n"
        f"⚠️ 1 подписка предназначена только для 1 устройства. При одновременном "
        f"включении на двух устройствах доступ автоматически блокируется."
    )
    await callback.message.edit_text(
        text,
        reply_markup=manage_keyboard(
            has_config=bool(sub.awg_config), is_active=sub.status == "active", protocol=sub.protocol
        ),
    )


@router.callback_query(F.data == "menu:referral")
async def referral(callback: CallbackQuery, session: AsyncSession) -> None:
    me = await callback.bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{callback.from_user.id}"

    invited_count = await session.scalar(
        select(func.count()).select_from(User).where(User.referrer_id == callback.from_user.id)
    )
    paid_count = await session.scalar(
        select(func.count(func.distinct(Payment.user_id)))
        .select_from(Payment)
        .join(User, User.tg_id == Payment.user_id)
        .where(User.referrer_id == callback.from_user.id, Payment.status == "paid")
    )
    bonuses = await session.execute(
        select(ReferralBonus).where(ReferralBonus.referrer_id == callback.from_user.id)
    )
    bonuses = bonuses.scalars().all()
    total_days = sum(b.bonus_days for b in bonuses)
    total_amount = sum(b.bonus_amount for b in bonuses)

    text = (
        "🎁 Бонус за друга\n\n"
        f"Получайте {settings.REFERRAL_BONUS_PERCENT}% с каждой покупки приглашённого друга "
        f"+ {settings.REFERRAL_BONUS_DAYS} дня подписки на баланс — за каждую его оплату, не только за первую.\n\n"
        f"Ваша ссылка:\n{link}\n\n"
        f"Приглашено: {invited_count or 0}\n"
        f"Оплатили подписку: {paid_count or 0}\n"
        f"Заработано: {total_amount} руб." + (f", {total_days} дн." if total_days else "")
    )
    await callback.message.edit_text(text, reply_markup=back_to_menu())
    await callback.answer()
