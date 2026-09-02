from __future__ import annotations

import uuid

from bot.services.payments.base import Invoice, PaymentProvider


class ManualProvider(PaymentProvider):
    """MVP payment provider used until a real gateway (AuraPay/Platega/CryptoBot/Stars) is wired in.

    No external API is called. The bot shows the user an "I've paid" button and
    notifies the admin, who confirms the payment from the admin panel. That
    confirmation directly flips the Payment row to `paid` in the DB (see
    handlers/purchase.py), so `is_paid` here is intentionally unused by the
    purchase flow and only kept to satisfy the interface.
    """

    name = "manual"

    async def create_invoice(self, *, user_id: int, amount: int, description: str) -> Invoice:
        return Invoice(invoice_id=str(uuid.uuid4()), pay_url=None, amount=amount)

    async def is_paid(self, invoice_id: str) -> bool:
        return False
