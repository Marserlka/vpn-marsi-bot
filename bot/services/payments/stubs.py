from __future__ import annotations

from bot.services.payments.base import Invoice, PaymentProvider


class _NotYetIntegrated(PaymentProvider):
    """Placeholder for a real gateway. Implement `create_invoice`/`is_paid`
    against the provider's API and register the instance in
    `bot.services.payments.PROVIDERS` when ready for stage 2.
    """

    async def create_invoice(self, *, user_id: int, amount: int, description: str) -> Invoice:
        raise NotImplementedError(f"{self.name} is not integrated yet")

    async def is_paid(self, invoice_id: str) -> bool:
        raise NotImplementedError(f"{self.name} is not integrated yet")


class AuraPayProvider(_NotYetIntegrated):
    name = "aurapay"


class PlategaProvider(_NotYetIntegrated):
    name = "platega"


class CryptoBotProvider(_NotYetIntegrated):
    name = "cryptobot"


class TelegramStarsProvider(_NotYetIntegrated):
    name = "stars"
