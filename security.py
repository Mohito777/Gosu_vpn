"""
Security module — антиабуз защита для VPN бота.

Функции:
  - Rate limiting (ограничение запросов)
  - Защита от спама командами
  - Чёрный список пользователей
  - Детекция подозрительных действий
  - Временные блокировки
"""

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Set, Dict, List
from aiogram import types
from aiogram.types import Message, CallbackQuery
from logger import get_logger
import config

log = get_logger("security")


# ── Constants ─────────────────────────────────────────────────────────────────

class ViolationType(Enum):
    SPAM = "spam"
    FLOOD = "flood"
    ABUSE = "abuse"
    SUSPICIOUS = "suspicious"
    PAYMENT_FRAUD = "payment_fraud"


@dataclass
class Violation:
    type: ViolationType
    timestamp: float
    details: str = ""


@dataclass
class UserInfo:
    telegram_id: int
    username: Optional[str] = None
    request_times: List[float] = field(default_factory=list)
    command_times: List[float] = field(default_factory=list)
    callback_times: List[float] = field(default_factory=list)
    violations: List[Violation] = field(default_factory=list)
    blocked_until: Optional[float] = None
    warning_count: int = 0
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)


# ── Rate Limiting Config ──────────────────────────────────────────────────────

@dataclass
class RateLimitConfig:
    # Максимум запросов в секунду
    requests_per_second: float = 2.0
    # Максимум запросов в минуту
    requests_per_minute: int = 30
    # Максимум команд в минуту
    commands_per_minute: int = 10
    # Максимум callback в минуту
    callbacks_per_minute: int = 20
    # Порог нарушений для блокировки
    violations_before_ban: int = 5
    # Время блокировки после нарушений (минуты)
    ban_duration_minutes: int = 60
    # Время жизни истории запросов (секунды)
    history_ttl: int = 120


# ── Security Manager ──────────────────────────────────────────────────────────

class SecurityManager:
    """
    Менеджер безопасности для защиты от абуза.
    Thread-safe (использует asyncio locks).
    """

    def __init__(self, rate_config: RateLimitConfig = None):
        self.config = rate_config or RateLimitConfig()
        self._users: Dict[int, UserInfo] = {}
        self._lock = asyncio.Lock()
        self._blacklist: Set[int] = set()
        # Безопасное получение ADMIN_IDS из config модуля
        try:
            import config as app_config
            self._admin_ids: Set[int] = set(app_config.ADMIN_IDS) if app_config.ADMIN_IDS else set()
        except (AttributeError, TypeError, ImportError):
            self._admin_ids: Set[int] = set()

        # Статистика
        self._total_blocked = 0
        self._total_warnings = 0
        self._violations_count: Dict[ViolationType, int] = defaultdict(int)

    async def get_user(self, telegram_id: int, username: str = None) -> UserInfo:
        """Получить или создать информацию о пользователе."""
        async with self._lock:
            if telegram_id not in self._users:
                self._users[telegram_id] = UserInfo(
                    telegram_id=telegram_id,
                    username=username
                )
            elif username:
                self._users[telegram_id].username = username
            
            user = self._users[telegram_id]
            user.last_activity = time.time()
            return user

    async def check_rate_limit(
        self,
        telegram_id: int,
        username: str = None,
        event_type: str = "message"
    ) -> tuple[bool, Optional[str]]:
        """
        Проверить rate limiting для пользователя.
        
        Returns:
            (allowed, reason) — True если запрос разрешён
        """
        # Админов не ограничиваем
        if telegram_id in self._admin_ids:
            return True, None

        async with self._lock:
            user = await self.get_user(telegram_id, username)
            now = time.time()

            # Проверка блокировки
            if user.blocked_until and now < user.blocked_until:
                remaining = int(user.blocked_until - now)
                return False, f"⛔️ Вы заблокированы на {remaining} сек."

            # Очистка старых записей
            cutoff = now - self.config.history_ttl
            user.request_times = [t for t in user.request_times if t > cutoff]
            user.command_times = [t for t in user.command_times if t > cutoff]
            user.callback_times = [t for t in user.callback_times if t > cutoff]

            # Проверка requests per second
            recent_requests = [t for t in user.request_times if now - t < 1.0]
            if len(recent_requests) >= self.config.requests_per_second:
                await self._record_violation(user, ViolationType.FLOOD, "Too many requests per second")
                return False, "⚠️ Слишком много запросов. Подождите немного."

            # Проверка requests per minute
            if len(user.request_times) >= self.config.requests_per_minute:
                await self._record_violation(user, ViolationType.FLOOD, "Too many requests per minute")
                return False, "⚠️ Превышен лимит запросов в минуту."

            # Проверка команд
            if event_type == "command":
                if len(user.command_times) >= self.config.commands_per_minute:
                    await self._record_violation(user, ViolationType.SPAM, "Too many commands")
                    return False, "⚠️ Слишком много команд."

            # Проверка callback
            if event_type == "callback":
                if len(user.callback_times) >= self.config.callbacks_per_minute:
                    await self._record_violation(user, ViolationType.SPAM, "Too many callbacks")
                    return False, "⚠️ Слишком много нажатий кнопок."

            # Запись запроса
            user.request_times.append(now)
            if event_type == "command":
                user.command_times.append(now)
            elif event_type == "callback":
                user.callback_times.append(now)

            return True, None

    async def _record_violation(
        self,
        user: UserInfo,
        violation_type: ViolationType,
        details: str
    ):
        """Записать нарушение и применить санкции."""
        now = time.time()
        violation = Violation(
            type=violation_type,
            timestamp=now,
            details=details
        )
        user.violations.append(violation)
        user.warning_count += 1

        self._violations_count[violation_type] += 1
        self._total_warnings += 1

        # Очистка старых нарушений (старше 1 часа)
        cutoff = now - 3600
        user.violations = [v for v in user.violations if v.timestamp > cutoff]

        # Проверка на блокировку
        if len(user.violations) >= self.config.violations_before_ban:
            ban_seconds = self.config.ban_duration_minutes * 60
            user.blocked_until = now + ban_seconds
            self._total_blocked += 1

            log.warning(
                f"User blocked: tg={user.telegram_id} "
                f"violations={len(user.violations)} duration={ban_seconds}s"
            )

            # Уведомление админам
            await self._notify_admins(user, violation_type, details)

        log.info(
            f"Violation recorded: tg={user.telegram_id} "
            f"type={violation_type.value} count={user.warning_count}"
        )

    async def _notify_admins(
        self,
        user: UserInfo,
        violation_type: ViolationType,
        details: str
    ):
        """Уведомить админов о серьёзном нарушении."""
        # Логгируем для последующей отправки
        log.critical(
            f"SECURITY ALERT: User @{user.username or user.telegram_id} "
            f"blocked for {violation_type.value}: {details}"
        )

    async def block_user(
        self,
        telegram_id: int,
        duration_minutes: int = None,
        reason: str = ""
    ):
        """Заблокировать пользователя вручную."""
        async with self._lock:
            user = await self.get_user(telegram_id)
            duration = duration_minutes or self.config.ban_duration_minutes
            user.blocked_until = time.time() + (duration * 60)
            self._blacklist.add(telegram_id)
            self._total_blocked += 1

            log.warning(f"User manually blocked: tg={telegram_id} reason={reason}")

    async def unblock_user(self, telegram_id: int):
        """Разблокировать пользователя."""
        async with self._lock:
            if telegram_id in self._users:
                self._users[telegram_id].blocked_until = None
            self._blacklist.discard(telegram_id)

            log.info(f"User unblocked: tg={telegram_id}")

    async def add_to_blacklist(self, telegram_id: int):
        """Добавить в чёрный список."""
        async with self._lock:
            self._blacklist.add(telegram_id)
            if telegram_id in self._users:
                self._users[telegram_id].blocked_until = None  # Перманентная блокировка

            log.warning(f"User added to blacklist: tg={telegram_id}")

    async def remove_from_blacklist(self, telegram_id: int):
        """Удалить из чёрного списка."""
        async with self._lock:
            self._blacklist.discard(telegram_id)
            log.info(f"User removed from blacklist: tg={telegram_id}")

    def is_blacklisted(self, telegram_id: int) -> bool:
        """Проверить, в чёрном ли списке пользователь."""
        return telegram_id in self._blacklist

    async def reset_user_history(self, telegram_id: int):
        """Очистить историю нарушений пользователя."""
        async with self._lock:
            if telegram_id in self._users:
                user = self._users[telegram_id]
                user.violations = []
                user.warning_count = 0
                user.blocked_until = None
                log.info(f"User violations reset: tg={telegram_id}")

    def get_stats(self) -> dict:
        """Получить статистику безопасности."""
        return {
            "total_users": len(self._users),
            "total_blocked": self._total_blocked,
            "total_warnings": self._total_warnings,
            "blacklist_size": len(self._blacklist),
            "violations_by_type": dict(self._violations_count),
            "currently_blocked": sum(
                1 for u in self._users.values()
                if u.blocked_until and time.time() < u.blocked_until
            ),
        }

    async def cleanup_inactive_users(self, max_age_days: int = 30):
        """Очистить данные о неактивных пользователях."""
        async with self._lock:
            now = time.time()
            cutoff = now - (max_age_days * 86400)

            to_remove = [
                tid for tid, user in self._users.items()
                if user.last_activity < cutoff
                and not user.blocked_until
                and tid not in self._admin_ids
            ]

            for tid in to_remove:
                del self._users[tid]

            log.info(f"Cleaned up {len(to_remove)} inactive users")


# ── Middleware ────────────────────────────────────────────────────────────────

class SecurityMiddleware:
    """
    Middleware для проверки безопасности.
    """

    def __init__(self, security_manager: SecurityManager):
        self.security = security_manager

    async def __call__(
        self,
        handler,
        event: Message | CallbackQuery,
        data: dict
    ):
        from_user = event.from_user
        telegram_id = from_user.id
        username = from_user.username

        # Логирование всех событий
        log.info(f"Security: tg={telegram_id} username={username} event={type(event).__name__}")

        # Админов не ограничиваем
        if telegram_id in self.security._admin_ids:
            log.info(f"Security admin bypass: tg={telegram_id}")
            return await handler(event, data)

        # Чёрный список
        if self.security.is_blacklisted(telegram_id):
            log.warning(f"Blacklisted user blocked: tg={telegram_id}")
            return

        # Callback query пропускаем без rate limiting (для кнопок)
        if isinstance(event, CallbackQuery):
            log.info(f"Security callback allowed: tg={telegram_id}")
            return await handler(event, data)

        # Определение типа события для message
        if isinstance(event, Message):
            if event.text and event.text.startswith("/"):
                event_type = "command"
            else:
                event_type = "message"
        else:
            event_type = "other"

        # Проверка rate limiting только для сообщений
        allowed, reason = await self.security.check_rate_limit(
            telegram_id,
            username,
            event_type
        )

        if not allowed:
            log.warning(f"Rate limit blocked: tg={telegram_id} reason={reason}")
            if isinstance(event, Message):
                try:
                    await event.answer(reason)
                except Exception:
                    pass
            return

        log.info(f"Security OK: tg={telegram_id}")
        return await handler(event, data)


# ── Payment Fraud Detection ───────────────────────────────────────────────────

class PaymentFraudDetector:
    """
    Детектор подозрительных платёжных действий.
    """

    def __init__(self, security_manager: SecurityManager):
        self.security = security_manager
        self._payment_attempts: Dict[int, List[float]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def record_payment_attempt(
        self,
        telegram_id: int,
        amount: float,
        gateway: str
    ) -> tuple[bool, Optional[str]]:
        """
        Записать попытку оплаты и проверить на фрод.
        
        Returns:
            (allowed, reason)
        """
        async with self._lock:
            now = time.time()
            user = await self.security.get_user(telegram_id)

            # Очистка старых записей (1 час)
            cutoff = now - 3600
            self._payment_attempts[telegram_id] = [
                t for t in self._payment_attempts[telegram_id] if t > cutoff
            ]

            attempts = self._payment_attempts[telegram_id]

            # Больше 5 попыток оплаты в час — подозрительно
            if len(attempts) >= 5:
                await self.security._record_violation(
                    user,
                    ViolationType.PAYMENT_FRAUD,
                    f"Multiple payment attempts: {len(attempts) + 1}/hour"
                )
                return False, "⚠️ Слишком много попыток оплаты. Обратитесь в поддержку."

            self._payment_attempts[telegram_id].append(now)
            return True, None

    async def record_successful_payment(self, telegram_id: int):
        """Записать успешную оплату — очистить историю попыток."""
        async with self._lock:
            self._payment_attempts[telegram_id] = []


# ── Global Instance ───────────────────────────────────────────────────────────

# Глобальный менеджер безопасности
security_manager = SecurityManager()

# Middleware для интеграции
security_middleware = SecurityMiddleware(security_manager)

# Детектор фрода
payment_fraud_detector = PaymentFraudDetector(security_manager)


# ── Admin Commands Helpers ────────────────────────────────────────────────────

async def cmd_block_user(telegram_id: int, duration: int = 60, reason: str = ""):
    """Заблокировать пользователя (для админ-команд)."""
    await security_manager.block_user(telegram_id, duration, reason)
    log.info(f"User blocked via command: tg={telegram_id} duration={duration}m")


async def cmd_unblock_user(telegram_id: int):
    """Разблокировать пользователя (для админ-команд)."""
    await security_manager.unblock_user(telegram_id)
    log.info(f"User unblocked via command: tg={telegram_id}")


async def cmd_blacklist_add(telegram_id: int):
    """Добавить в чёрный список (для админ-команд)."""
    await security_manager.add_to_blacklist(telegram_id)
    log.info(f"User blacklisted via command: tg={telegram_id}")


async def cmd_blacklist_remove(telegram_id: int):
    """Удалить из чёрного списка (для админ-команд)."""
    await security_manager.remove_from_blacklist(telegram_id)
    log.info(f"User removed from blacklist via command: tg={telegram_id}")


def get_security_stats() -> dict:
    """Получить статистику безопасности (для админ-панели)."""
    return security_manager.get_stats()
