# VPN MARSI — Telegram-бот

Реализация по [TZ.md](TZ.md).

## Установка

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Заполните `.env`:
- `BOT_TOKEN` — токен от @BotFather.
- `ADMIN_IDS` — ваш Telegram ID (и других админов через запятую).
- `MARZBAN_*` — адрес и креды панели Marzban, а также тег inbound'а с VLESS-Reality.

Без заполненных `MARZBAN_*` бот всё равно запустится: ошибка вылезет только в момент реальной покупки (лог уйдёт в `errors.log`, пользователь получит вежливое сообщение об ошибке), это ожидаемо на этапе разработки без поднятого сервера.

## Запуск

```bash
python -m bot.main
```

## Текущий статус оплаты (важно)

Платёжный модуль реализован как абстракция (`bot/services/payments/base.py`). Сейчас подключён только `ManualProvider` — MVP-режим: пользователь жмёт «Я оплатил(а)», админ подтверждает платёж кнопкой в чате, после чего подписка активируется автоматически. Реальные шлюзы (AuraPay, Platega, CryptoBot, Telegram Stars) — заглушки в `bot/services/payments/stubs.py`, для боевого запуска каждую нужно реализовать по образцу `ManualProvider`, не трогая остальной код.

## Marzban: что проверить перед продакшеном

`bot/services/marzban.py` создаёт пользователя с полем `ips_limit=1` для ограничения "1 ключ = 1 устройство". Названия полей отличаются между версиями/форками Marzban — **обязательно** сверьтесь со Swagger-документацией вашей развёрнутой панели (`{MARZBAN_BASE_URL}/docs`) и поправьте `MarzbanClient.IP_LIMIT_FIELD` при необходимости, прежде чем полагаться на этот лимит в проде.

Также заранее настройте в самой панели Marzban inbound VLESS-Reality с маской (SNI/Dest) под vk.com / max.com / kinopoisk.ru — бот только передаёт тег этого inbound'а (`MARZBAN_INBOUND_TAG`), саму маскировку конфигурирует панель.

## Бэкапы БД

`scripts/backup_db.sh` — ежедневное копирование SQLite-файла с ротацией (хранит 30 дней). Добавьте в cron сервера:

```
0 3 * * * /path/to/VPN\ MARSI/scripts/backup_db.sh >> /var/log/vpnmarsi_backup.log 2>&1
```

## Структура проекта

См. план реализации — раздел "Структура проекта" в истории задачи, коротко:
- `bot/database/` — модели SQLAlchemy и инициализация БД.
- `bot/services/` — бизнес-логика (подписки, промокоды, рефералы) и интеграции (Marzban, платежи).
- `bot/handlers/` — хендлеры aiogram (клиентские + `bot/handlers/admin/` под `/admin`).
- `bot/scheduler/` — напоминания за 3/1 день и автоотключение по истечении.

## Чек-лист приёмки

Соответствует разделу 6 `TZ.md`. Пункты про реальный Marzban-сервер и боевые платёжные шлюзы можно проверить только после разворачивания панели на сервере Aurorix и подключения реальных API-ключей провайдеров — до этого момента тестируйте через `ManualProvider`.
