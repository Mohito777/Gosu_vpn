"""
APScheduler — ежедневная проверка истёкших подписок.
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
import database as db
from xui_api import xui
from logger import get_logger

log = get_logger("scheduler")

_scheduler = AsyncIOScheduler(timezone="UTC")
_bot = None


def set_bot(bot):
    global _bot
    _bot = bot


async def _notify(telegram_id: int, text: str):
    if _bot and telegram_id:
        try:
            await _bot.send_message(telegram_id, text)
        except Exception as e:
            log.warning(f"Notify failed for {telegram_id}: {e}")


async def check_expired_subscriptions():
    log.info("Scheduler: checking expired subscriptions...")
    expired = db.get_expired_users()
    log.info(f"Scheduler: found {len(expired)} expired users")

    for user in expired:
        telegram_id = user["telegram_id"]
        client_uuid = user["uuid"]
        username = user["username"] or str(telegram_id)

        if client_uuid:
            success = xui.delete_client(client_uuid)
            if success:
                log.info(f"Scheduler: deleted client uuid={client_uuid} tgid={telegram_id}")
            else:
                log.error(f"Scheduler: failed to delete client uuid={client_uuid} tgid={telegram_id}")
        else:
            log.warning(f"Scheduler: no uuid for tgid={telegram_id}, skipping xui delete")

        db.deactivate_user(telegram_id)
        await _notify(
            telegram_id,
            "⚠️ Ваша подписка истекла. Доступ отключён.\n\n"
            "Нажмите /start чтобы продлить.",
        )
        log.info(f"Scheduler: deactivated user tgid={telegram_id} username={username}")


def start(bot=None):
    if bot:
        set_bot(bot)
    _scheduler.add_job(
        check_expired_subscriptions,
        trigger="cron",
        hour=3,
        minute=0,
        id="expire_check",
        replace_existing=True,
    )
    _scheduler.start()
    log.info("Scheduler started — daily check at 03:00 UTC")


def stop():
    _scheduler.shutdown(wait=False)
    log.info("Scheduler stopped")
