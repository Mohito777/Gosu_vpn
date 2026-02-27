from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import config


def main_menu() -> ReplyKeyboardMarkup:
    """Главное меню с кнопками (для пользователей)."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="☰ Меню")],
            [KeyboardButton(text="📢 Канал"), KeyboardButton(text="💳 Тарифы и оплата")],
            [KeyboardButton(text="🔑 Мой ключ"), KeyboardButton(text="📊 Статус")],
            [KeyboardButton(text="ℹ️ О сервисе")],
            [KeyboardButton(text="👥 Рефералы")],
            [KeyboardButton(text="❓ Поддержка")],
        ],
        resize_keyboard=True,
    )


def admin_keyboard() -> ReplyKeyboardMarkup:
    """Админ-меню."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="👥 Пользователи")],
            [KeyboardButton(text="📩 Рассылка"), KeyboardButton(text="🎁 Промокоды")],
            [KeyboardButton(text="⚙️ Настройки"), KeyboardButton(text="🔙 Главное меню")],
        ],
        resize_keyboard=True,
    )


def plans_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    
    # Сначала бесплатный тариф (если настроен канал)
    if config.CHANNEL_ID and config.CHANNEL_ID != 0:
        buttons.append(
            [InlineKeyboardButton(
                text=f"🎁 {config.PLANS['free']['label']}",
                callback_data=f"plan:free",
            )]
        )
    
    # Платные тарифы
    for key, plan in config.PLANS.items():
        if key == "free":
            continue
        buttons.append(
            [InlineKeyboardButton(
                text=f"✅ {plan['label']}",
                callback_data=f"plan:{key}",
            )]
        )
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def payment_method_keyboard(plan_key: str) -> InlineKeyboardMarkup:
    plan = config.PLANS[plan_key]
    rows = []

    # Бесплатный тариф - сразу активация
    if plan_key == "free":
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="✅ Активировать бесплатно",
                callback_data=f"pay:free:{plan_key}",
            )],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back:plans")],
        ])

    # CryptoBot (if configured)
    if config.CRYPTOBOT_TOKEN:
        rows.append([InlineKeyboardButton(
            text=f"🪙 Крипто (USDT {plan['price_usdt']})",
            callback_data=f"pay:crypto:{plan_key}",
        )])

    # Paymaster (if configured)
    if config.PAYMASTER_TOKEN:
        rows.append([InlineKeyboardButton(
            text=f"💳 Карта / СБП {plan['price_rub']} ₽ (Paymaster)",
            callback_data=f"pay:paymaster:{plan_key}",
        )])

    # Lava.ru (if configured)
    if config.LAVA_SHOP_ID:
        rows.append([InlineKeyboardButton(
            text=f"💳 Карта / СБП {plan['price_rub']} ₽ (Lava)",
            callback_data=f"pay:lava:{plan_key}",
        )])

    # Manual payment (webhook-based generic)
    rows.append([InlineKeyboardButton(
        text=f"🏦 Перевод ({plan['price_rub']} ₽)",
        callback_data=f"pay:manual:{plan_key}",
    )])

    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back:plans")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_paid_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Я оплатил", callback_data="paid:confirm")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back:plans")],
    ])


def support_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✉️ Написать в поддержку", url="https://t.me/ElfVoin")],
    ])


def subscribe_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура с кнопкой подписки на канал."""
    channel = config.CHANNEL_USERNAME or "@your_channel"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Подписаться", url=f"https://t.me/{channel.lstrip('@')}")],
        [InlineKeyboardButton(text="✅ Я подписался", callback_data="check_subscribe")],
    ])


def referral_keyboard(referral_link: str) -> InlineKeyboardMarkup:
    """Клавиатура для реферальной программы."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Скопировать ссылку", url=referral_link)],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="referral_stats")],
    ])


def admin_inline_keyboard() -> InlineKeyboardMarkup:
    """Админ-меню inline."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users")],
        [InlineKeyboardButton(text="📩 Рассылка", callback_data="admin_mailing")],
        [InlineKeyboardButton(text="🎁 Промокоды", callback_data="admin_promocodes")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="admin_settings")],
    ])


def back_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура с кнопкой 'Назад'."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back:main")],
    ])
