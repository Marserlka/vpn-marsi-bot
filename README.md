# VPN MARSI — Telegram-бот

Реализация по [TZ.md](TZ.md). **Основной протокол — AmneziaWG** (см. TZ 3.2 для истории решения).

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
- `AWG_AGENT_BASE_URL` / `AWG_AGENT_TOKEN` — адрес и токен сервиса `awg_agent` на VPS (см. ниже).
- `MARZBAN_*` — не используется текущим потоком активации подписки, оставлено на будущее.

Без заполненных `AWG_AGENT_*` бот всё равно запустится: ошибка вылезет только в момент реальной покупки (лог уйдёт в `errors.log`, пользователь получит вежливое сообщение об ошибке).

## Запуск

```bash
python -m bot.main
```

## Текущий статус оплаты (важно)

Платёжный модуль реализован как абстракция (`bot/services/payments/base.py`). Сейчас подключён только `ManualProvider` — MVP-режим: пользователь жмёт «Я оплатил(а)», админ подтверждает платёж кнопкой в чате, после чего подписка активируется автоматически. Реальные шлюзы (AuraPay, Platega, CryptoBot, Telegram Stars) — заглушки в `bot/services/payments/stubs.py`, для боевого запуска каждую нужно реализовать по образцу `ManualProvider`, не трогая остальной код.

## AmneziaWG-агент на сервере (обязательно для выдачи ключей)

У AmneziaWG нет REST API, поэтому на VPS рядом с интерфейсом `awg0` крутится маленький HTTP-сервис `scripts/awg_agent.py` (systemd unit `awg-agent.service`, порт 9443, TLS на том же сертификате, что и панель). Бот дёргает его через `bot/services/awg_agent.py`:
- `POST /peers {"label": "..."}` — создаёт нового пира, возвращает готовый `.conf`.
- `DELETE /peers/<pubkey>` — удаляет пира (когда подписка истекла/отключена админом).

Состояние пиров хранится в `/etc/amnezia/amneziawg/peers.json` на сервере и синхронизируется с самим `awg0.conf`, так что список переживает перезапуск сервера.

Деплой на новый сервер: скопируйте `scripts/awg_agent.py` в `/opt/awg_agent.py`, поднимите его через systemd unit с обязательными переменными окружения (`AWG_AGENT_TOKEN`, `AWG_SERVER_ENDPOINT`, `AWG_SERVER_PUBLIC_KEY`, `AWG_TLS_CERTFILE`, `AWG_TLS_KEYFILE` — см. докстринг в начале файла).

## Marzban (не используется, задел на будущее)

Панель поднята, `bot/services/marzban.py` рабочий и протестирован (VLESS-Reality, маска под `addons.mozilla.org`, лимит по IP через `ips_limit` — но само поле в текущей версии Marzban не поддерживается, это выяснилось в проде). Бизнес-логика подписок (`bot/services/subscriptions.py`) сейчас его не вызывает — переключились на AmneziaWG после боевого теста (см. TZ 3.2). Если понадобится второй протокол, интеграция уже готова.

## Бэкапы БД

`scripts/backup_db.sh` — ежедневное копирование SQLite-файла с ротацией (хранит 30 дней). Добавьте в cron сервера:

```
0 3 * * * /path/to/VPN\ MARSI/scripts/backup_db.sh >> /var/log/vpnmarsi_backup.log 2>&1
```

Не забудьте также бэкапить `/etc/amnezia/amneziawg/peers.json` и `awg0.conf` на самом VPS — это отдельное состояние, не в SQLite бота.

## Структура проекта

- `bot/database/` — модели SQLAlchemy и инициализация БД (с лёгкой авто-миграцией недостающих колонок в `db.py`, без Alembic).
- `bot/services/` — бизнес-логика (подписки, промокоды, рефералы) и интеграции (`awg_agent.py` — основной протокол, `marzban.py` — задел на будущее, платежи).
- `bot/handlers/` — хендлеры aiogram (клиентские + `bot/handlers/admin/` под `/admin`).
- `bot/scheduler/` — напоминания за 3/1 день и автоотключение по истечении.
- `scripts/awg_agent.py` — HTTP-сервис управления AmneziaWG-пирами, деплоится на VPS отдельно от бота.

## Чек-лист приёмки

Соответствует разделу 6 `TZ.md`. Реально протестировано на боевом сервере (Нидерланды) и с реального устройства из России: выдача `.conf`, импорт в AmneziaVPN, доступ к Telegram/YouTube.
