# 🌐 ShadowLink VPN Bot

Telegram-бот для управления VPN-сервисом на базе 3x-ui (VLESS/Reality).

## ✨ Возможности

- 🎁 **Бесплатный тариф** — 30 дней за подписку на канал
- 💳 **Оплата** — CryptoBot, Lava, Paymaster, перевод по номеру (СБП)
- 🔑 **Ключи VLESS** — автоматическая генерация и выдача
- 👥 **Реферальная система** — бонусы за приглашённых друзей
- 📊 **Статистика** — трафик, остаток дней, статус подписки
- 🔒 **VLESS + Reality** — современный протокол для обхода блокировок

## 🚀 Быстрый старт

### Требования

- Python 3.10+
- 3x-ui панель (Hiddify/Alireza)
- Telegram Bot Token (@BotFather)

### Установка

1. **Клонируйте репозиторий:**
```bash
git clone https://github.com/Mohito777/VPN_bot.git
cd VPN_bot
```

2. **Создайте виртуальное окружение:**
```bash
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# или
venv\Scripts\activate  # Windows
```

3. **Установите зависимости:**
```bash
pip install -r requirements.txt
```

4. **Настройте `.env`:**
```bash
cp .env.example .env
nano .env  # отредактируйте значения
```

5. **Запустите бота:**
```bash
python3 bot.py
```

## ⚙️ Настройка

### Telegram Bot
1. Создайте бота в [@BotFather](https://t.me/BotFather)
2. Получите токен
3. Добавьте в `.env`: `BOT_TOKEN=ваш_токен`

### 3x-ui Panel
1. Установите панель (например, [Hiddify](https://github.com/hiddify/hiddify-config))
2. Создайте inbound с протоколом VLESS Reality
3. Добавьте в `.env`:
```env
XUI_URL=http://your-server:54321
XUI_USERNAME=admin
XUI_PASSWORD=your_password
XUI_INBOUND_ID=1
```

### Канал для подписки
1. Создайте канал
2. Добавьте бота как администратора
3. Добавьте в `.env`:
```env
CHANNEL_USERNAME=@your_channel
CHANNEL_ID=-1001234567890
```

### Платёжные системы

#### CryptoBot (криптовалюта)
- Токен: @CryptoBot → /newapp
- `CRYPTOBOT_TOKEN=ваш_токен`

#### Lava (карты/СБП)
- Регистрация: https://lava.ru
- `LAVA_SHOP_ID=ваш_id`
- `LAVA_SECRET_KEY=ваш_ключ`

#### Paymaster (VK Pay)
- Регистрация: https://paymaster.ru
- `PAYMASTER_TOKEN=ваш_токен`
- `PAYMASTER_MERCHANT_ID=ваш_id`

#### Ручной перевод (СБП)
- `MANUAL_PAYMENT_PHONE=+79991234567`

## 📁 Структура проекта

```
VPN_bot/
├── bot.py              # Основной бот
├── config.py           # Конфигурация
├── database.py         # База данных (SQLite)
├── keyboards.py        # Клавиатуры
├── admin.py            # Админ-панель
├── webhook.py          # Webhook-сервер для платежей
├── scheduler.py        # Планировщик (проверка подписок)
├── xui_api.py          # API для 3x-ui
├── payments/           # Платёжные модули
│   ├── cryptobot.py
│   ├── lava.py
│   └── paymaster.py
├── .env                # Конфигурация (не коммитить!)
├── .env.example        # Пример конфигурации
└── requirements.txt    # Зависимости
```

## 🔧 Админ-команды

- `/admin` — Админ-панель
- `/stats` — Статистика
- `/grant <tg_id> <plan> <payment_id>` — Выдать доступ
- `/user <tg_id>` — Информация о пользователе
- `/set_channel @username` — Установить канал
- `/set_trial_days N` — Длительность триала
- `/promo create CODE DAYS` — Создать промокод

## 🎁 Тарифы (по умолчанию)

| Тариф | Дней | Цена (₽) | Цена (USDT) |
|-------|------|----------|-------------|
| Free  | 30   | 0        | 0.00        |
| 1 мес | 30   | 100      | 1.50        |
| 2 мес | 60   | 200      | 3.00        |
| 3 мес | 90   | 300      | 4.50        |
| 6 мес | 180  | 600      | 9.00        |
| 12 мес| 365  | 1200     | 18.00       |

## 📱 Приложения для подключения

### Android
- [v2rayNG](https://github.com/2dust/v2rayNG/releases) — GitHub
- [V2Box](https://play.google.com/store/apps/details?id=dev.hexasoftware.v2box) — Google Play
- [Hiddify](https://play.google.com/store/apps/details?id=app.hiddify.com) — Google Play

### iOS
- [Streisand](https://apps.apple.com/app/streisand/id6450534064) — App Store
- [Hiddify](https://apps.apple.com/us/app/hiddify-proxy-vpn/id6596777532) — App Store

### Windows / Mac / Linux
- [Hiddify](https://github.com/hiddify/hiddify-next/releases) — GitHub
- [v2rayN](https://github.com/2dust/v2rayN/releases) — GitHub (Windows)
- [Nekoray](https://github.com/MatsuriDayo/nekoray/releases) — GitHub

## 🔒 Безопасность

⚠️ **Важно:** Файл `.env` содержит секретные ключи и **не должен** коммититься в Git!

Проект включает `.gitignore` для защиты:
- `.env` — токены, пароли, номера телефонов
- `*.db` — база данных пользователей
- `*.log` — логи бота

## 📝 Changelog

См. [CHANGELOG.md](CHANGELOG.md)

## 🤝 Поддержка

- Канал: [@shadowlink_top](https://t.me/shadowlink_top)
- Telegram: [@ElfVoin](https://t.me/ElfVoin)

## 📄 Лицензия

MIT

---

**ShadowLink** — ваш приватный канал в свободный интернет 🌐
