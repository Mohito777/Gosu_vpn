"""
Middlewares для проверки подписки на канал и других проверок.
"""

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from typing import Callable, Dict, Any, Awaitable, Optional
from logger import get_logger
import database as db
import config

log = get_logger("middlewares")

# Глобальная переменная для bot (устанавливается в bot.py)
_bot_instance = None


def set_bot(bot):
    """Установить экземпляр бота для использования в middleware."""
    global _bot_instance
    _bot_instance = bot


class SubscriptionMiddleware(BaseMiddleware):
    """
    Middleware для проверки подписки пользователя на канал.
    Если не подписан — блокирует доступ к функциям бота.
    """

    def __init__(self):
        # bot берётся из глобальной переменной _bot_instance
        pass

    @property
    def bot(self):
        """Получить текущий экземпляр бота."""
        return _bot_instance

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any]
    ) -> Any:
        from_user = event.from_user

        # Логирование всех событий
        log.info(f"Middleware: tg={from_user.id} username={from_user.username} event={type(event).__name__}")

        # Пропускаем для админов
        if from_user.id in config.ADMIN_IDS:
            log.info(f"Admin bypass: tg={from_user.id}")
            return await handler(event, data)

        # Пропускаем команду /start
        if isinstance(event, Message) and event.text:
            if event.text.startswith("/start"):
                log.info(f"/start command allowed: tg={from_user.id}")
                return await handler(event, data)

        # ВСЕ Callback query пропускаем без проверки подписки
        # Проверка подписки только для текстовых сообщений
        if isinstance(event, CallbackQuery):
            log.info(f"Callback query allowed (no sub check): tg={from_user.id} data={event.data}")
            return await handler(event, data)

        # Проверяем подписку для сообщений
        is_subscribed = await self._check_subscription(from_user.id)
        log.info(f"Subscription check result: tg={from_user.id} subscribed={is_subscribed}")
        
        if not is_subscribed:
            await self._send_subscription_request(event)
            log.info(f"Subscription request sent: tg={from_user.id}")
            return None

        log.info(f"Subscription OK: tg={from_user.id}")
        return await handler(event, data)
    
    async def _check_subscription(self, telegram_id: int) -> bool:
        """Проверка подписки через Telegram API и БД."""
        try:
            # Сначала проверяем в БД (кэш)
            if db.is_user_subscribed(telegram_id):
                # Перепроверяем через Telegram API
                member = await self._get_chat_member(telegram_id)
                if member and member.status in ["member", "administrator", "creator"]:
                    return True
                # Если отписался — обновляем БД
                db.set_user_subscribed(telegram_id, False)
                return False
            
            # Проверяем через Telegram API
            member = await self._get_chat_member(telegram_id)
            if member and member.status in ["member", "administrator", "creator"]:
                db.set_user_subscribed(telegram_id, True)
                return True
            
            return False
        except Exception as e:
            log.error(f"Subscription check error for {telegram_id}: {e}")
            # В случае ошибки — пропускаем (fail-open)
            return True
    
    async def _get_chat_member(self, telegram_id: int):
        """Получение статуса участника канала."""
        if not config.CHANNEL_ID or config.CHANNEL_ID == 0:
            return None

        if not self.bot:
            log.warning(f"Bot instance not set, cannot check chat member for tg={telegram_id}")
            return None

        try:
            return await self.bot.get_chat_member(config.CHANNEL_ID, telegram_id)
        except Exception as e:
            log.error(f"get_chat_member error: {e}")
            return None
    
    async def _send_subscription_request(self, message: Message):
        """Отправка сообщения с просьбой подписаться."""
        from keyboards import subscribe_keyboard
        
        channel = config.CHANNEL_USERNAME or "@your_channel"
        text = (
            "⚠️ <b>Для доступа к функциям бота необходимо подписаться на канал</b>\n\n"
            f"📢 Подпишитесь на наш канал: {channel}\n\n"
            "После подписки нажмите кнопку ниже:"
        )
        
        await message.answer(
            text,
            reply_markup=subscribe_keyboard(),
            parse_mode="html"
        )


def check_subscription_required(handler_name: str = "") -> bool:
    """
    Декоратор для отдельных хендлеров, требующих подписки.
    Используется как альтернатива middleware.
    """
    async def wrapper(
        handler: Callable,
        event: Message | CallbackQuery,
        data: Dict[str, Any]
    ):
        telegram_id = event.from_user.id
        
        # Пропускаем админов
        if telegram_id in config.ADMIN_IDS:
            return await handler(event, data)
        
        if not db.is_user_subscribed(telegram_id):
            if isinstance(event, Message):
                channel = config.CHANNEL_USERNAME or "@your_channel"
                from keyboards import subscribe_keyboard
                await message.answer(
                    f"⚠️ Сначала подпишитесь на канал: {channel}",
                    reply_markup=subscribe_keyboard()
                )
                return None
            elif isinstance(event, CallbackQuery):
                await event.answer("⚠️ Сначала подпишитесь на канал!", show_alert=True)
                return None
        
        return await handler(event, data)
    
    return wrapper
