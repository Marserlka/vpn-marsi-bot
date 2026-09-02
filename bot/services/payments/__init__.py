from bot.services.payments.base import PaymentProvider
from bot.services.payments.manual import ManualProvider

PROVIDERS: dict[str, PaymentProvider] = {
    "manual": ManualProvider(),
}

DEFAULT_PROVIDER = "manual"
