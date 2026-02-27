import os
from dotenv import load_dotenv

load_dotenv()

# ── Telegram ────────────────────────────────────────────────────────────────
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
ADMIN_IDS: list[int] = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

# ── Channel / Group for subscription check ──────────────────────────────────
CHANNEL_USERNAME: str = os.getenv("CHANNEL_USERNAME", "@shadowlink_top")  # Канал для обязательной подписки
CHANNEL_ID: int = int(os.getenv("CHANNEL_ID", "0"))  # ID канала (число, например -1001234567890)

# ── 3x-ui panel ─────────────────────────────────────────────────────────────
XUI_URL: str = os.getenv("XUI_URL", "http://localhost:54321")
XUI_USERNAME: str = os.getenv("XUI_USERNAME", "admin")
XUI_PASSWORD: str = os.getenv("XUI_PASSWORD", "admin")
XUI_INBOUND_ID: int = int(os.getenv("XUI_INBOUND_ID", "1"))

# ── Webhook server ───────────────────────────────────────────────────────────
WEBHOOK_HOST: str = os.getenv("WEBHOOK_HOST", "0.0.0.0")
WEBHOOK_PORT: int = int(os.getenv("WEBHOOK_PORT", "8080"))
PAYMENT_SECRET_KEY: str = os.getenv("PAYMENT_SECRET_KEY", "changeme")

# ── CryptoBot (Telegram) ─────────────────────────────────────────────────────
CRYPTOBOT_TOKEN: str = os.getenv("CRYPTOBOT_TOKEN", "")
CRYPTOBOT_NETWORK: str = os.getenv("CRYPTOBOT_NETWORK", "mainnet")

# ── Lava.ru (SBP / карты без ИП / самозанятости) ────────────────────────────
LAVA_SHOP_ID: str = os.getenv("LAVA_SHOP_ID", "")
LAVA_SECRET_KEY: str = os.getenv("LAVA_SECRET_KEY", "")

# ── Manual payment (перевод по номеру телефона) ─────────────────────────────
MANUAL_PAYMENT_PHONE: str = os.getenv("MANUAL_PAYMENT_PHONE", "+79615160441")

# ── Paymaster.ru (VK Pay) ────────────────────────────────────────────────────
PAYMASTER_TOKEN: str = os.getenv("PAYMASTER_TOKEN", "")  # Тестовый: 1744374395:TEST:...
PAYMASTER_MERCHANT_ID: str = os.getenv("PAYMASTER_MERCHANT_ID", "")  # ID магазина

# ── Тарифы (обновлённые) ───────────────────────────────────────────────────
PLANS: dict[str, dict] = {
    # Акция: 1 месяц бесплатно за подписку на канал
    "free": {"days": 30, "price_rub": 0, "price_usdt": "0.00", "label": "🎁 1 месяц (за подписку)"},
    # Базовый тариф
    "30":  {"days": 30, "price_rub": 100, "price_usdt": "1.50", "label": "1 месяц — 100 ₽"},
    # Остальные тарифы
    "60":  {"days": 60, "price_rub": 200, "price_usdt": "3.00", "label": "2 месяца — 200 ₽"},
    "90":  {"days": 90, "price_rub": 300, "price_usdt": "4.50", "label": "3 месяца — 300 ₽"},
    "120": {"days": 120, "price_rub": 400, "price_usdt": "6.00", "label": "4 месяца — 400 ₽"},
    "150": {"days": 150, "price_rub": 500, "price_usdt": "7.50", "label": "5 месяцев — 500 ₽"},
    "180": {"days": 180, "price_rub": 600, "price_usdt": "9.00", "label": "6 месяцев — 600 ₽"},
    "365": {"days": 365, "price_rub": 1200, "price_usdt": "18.00", "label": "12 месяцев — 1 200 ₽"},
}

# ── Trial settings ───────────────────────────────────────────────────────────
TRIAL_ENABLED: bool = os.getenv("TRIAL_ENABLED", "true").lower() == "true"
TRIAL_DAYS: int = int(os.getenv("TRIAL_DAYS", "1"))

# ── Referral settings ────────────────────────────────────────────────────────
REFERRAL_BONUS_DAYS: int = int(os.getenv("REFERRAL_BONUS_DAYS", "3"))  # Дней бонуса за реферала

# ── Validate required env vars ────────────────────────────────────────────────
REQUIRED = ["BOT_TOKEN", "XUI_URL", "XUI_USERNAME", "XUI_PASSWORD", "XUI_INBOUND_ID", "PAYMENT_SECRET_KEY"]

def validate():
    missing = [k for k in REQUIRED if not os.getenv(k)]
    if missing:
        raise EnvironmentError(f"Missing required environment variables: {', '.join(missing)}")
