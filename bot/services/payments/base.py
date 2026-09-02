from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Invoice:
    invoice_id: str
    pay_url: str | None  # None for providers that settle inside Telegram (e.g. manual/Stars)
    amount: int


class PaymentProvider(ABC):
    """Common interface every payment gateway integration must implement.

    Business logic (bot.services.subscriptions) only talks to this interface,
    so plugging in a real gateway later (AuraPay/Platega/CryptoBot/Stars) never
    requires touching purchase flow or handlers — only a new class here.
    """

    name: str

    @abstractmethod
    async def create_invoice(self, *, user_id: int, amount: int, description: str) -> Invoice:
        """Create a payment intent and return its invoice details."""

    @abstractmethod
    async def is_paid(self, invoice_id: str) -> bool:
        """Check (or receive via webhook, cached) whether the invoice was paid."""
