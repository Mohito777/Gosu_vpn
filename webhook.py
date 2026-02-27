"""
Webhook server (aiohttp) — принимает POST-уведомления от платёжных шлюзов.
Endpoints:
  POST /webhook/generic   — универсальный шлюз (payment_id, telegram_id, amount, status, secret)
  POST /webhook/crypto    — CryptoBot Telegram
  POST /webhook/lava      — Lava.ru

Запуск отдельно от бота:
  python webhook.py
"""

import asyncio
import json
from aiohttp import web
from aiogram.enums import ParseMode

import config
import database as db
from xui_api import xui
from logger import get_logger
import payments.cryptobot as cryptobot
import payments.lava as lava
import payments.paymaster as paymaster

log = get_logger("webhook")

# Bot instance injected at startup for user notifications
_bot = None


def set_bot(bot):
    global _bot
    _bot = bot


async def _notify_user(telegram_id: int, text: str):
    if _bot and telegram_id:
        try:
            await _bot.send_message(telegram_id, text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        except Exception as e:
            log.warning(f"Failed to notify user {telegram_id}: {e}")


async def _grant_access(telegram_id: int, plan_key: str, payment_id: str, gateway: str, amount: float) -> bool:
    """
    Central access-granting function with anti-duplicate protection.
    Returns True if access was granted, False if duplicate/error.
    """
    # Anti-duplicate: check payment_log
    if db.is_payment_processed(payment_id):
        log.warning(f"Duplicate payment ignored: payment_id={payment_id}")
        return False

    user = db.get_user(telegram_id)
    if not user:
        log.warning(f"Payment for unknown user: telegram_id={telegram_id}")
        db.log_payment(payment_id, telegram_id, amount, "unknown_user", gateway)
        return False

    # If already active with this exact payment — skip
    if user["active"] == 1 and user["last_payment_id"] == payment_id:
        log.warning(f"User already active with same payment_id={payment_id}")
        return False

    plan = config.PLANS.get(plan_key)
    if not plan:
        log.error(f"Unknown plan_key={plan_key} for payment_id={payment_id}")
        db.log_payment(payment_id, telegram_id, amount, "unknown_plan", gateway)
        return False

    days = plan["days"]
    client_uuid = user["uuid"] or xui.generate_uuid()

    # Add to 3x-ui (idempotent: if exists — skip add, just update DB)
    if not xui.client_exists(client_uuid):
        email = f"tg{telegram_id}"
        success = xui.add_client(client_uuid, email, days)
        if not success:
            log.error(f"Failed to add client in 3x-ui: telegram_id={telegram_id}")
            db.log_payment(payment_id, telegram_id, amount, "xui_error", gateway)
            return False

    db.activate_user(telegram_id, client_uuid, days, payment_id)
    db.log_payment(payment_id, telegram_id, amount, "success", gateway)

    # Build connection link if possible
    conn_link = xui.get_client_config_link(client_uuid, f"VPN_{telegram_id}")
    if conn_link:
        msg = (
            f"✅ <b>Оплата подтверждена! Доступ выдан.</b>\n\n"
            f"📦 Тариф: {plan['label']}\n"
            f"⏳ Действует: {days} дн.\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🔑 <b>Ваш ключ подключения:</b>\n"
            f"<code>{conn_link}</code>\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📲 <b>Скопируйте ключ и вставьте в приложение:</b>\n\n"
            f"<b>Android:</b>\n"
            f"• <a href='https://play.google.com/store/apps/details?id=com.v2ray.ang'>v2rayNG</a> (Google Play)\n"
            f"• <a href='https://github.com/hiddify/hiddify-next/releases'>Hiddify</a> (GitHub)\n"
            f"• <a href='https://github.com/MatsuriDayo/nekoray/releases'>Nekoray</a> (GitHub)\n\n"
            f"<b>iOS:</b>\n"
            f"• <a href='https://apps.apple.com/app/streisand/id6450534064'>Streisand</a> (App Store)\n"
            f"• <a href='https://apps.apple.com/app/foxy-proxy/id6476592498'>Foxy Proxy</a> (App Store)\n"
            f"• <a href='https://apps.apple.com/app/v2box-v2ray-client/id6444125698'>V2Box</a> (App Store)\n\n"
            f"<b>Windows / Mac / Linux:</b>\n"
            f"• <a href='https://github.com/hiddify/hiddify-next/releases'>Hiddify</a> (GitHub)\n"
            f"• <a href='https://github.com/2dust/v2rayN/releases'>v2rayN</a> (GitHub, Windows)\n"
            f"• <a href='https://github.com/MatsuriDayO/nekoray/releases'>Nekoray</a> (GitHub)"
        )
    else:
        msg = f"✅ <b>Оплата подтверждена! Доступ выдан на {days} дней.</b>\n\nНапишите /start → 🔑 <b>Мой ключ</b>."

    await _notify_user(telegram_id, msg)
    log.info(f"Access granted: telegram_id={telegram_id} plan={plan_key} days={days} payment_id={payment_id}")
    return True


# ── Generic webhook ───────────────────────────────────────────────────────────

async def handle_generic(request: web.Request) -> web.Response:
    """
    Universal webhook: { payment_id, telegram_id, amount, status, plan_key, secret }
    """
    try:
        body = await request.json()
    except Exception:
        log.warning("Generic webhook: invalid JSON")
        return web.Response(status=400, text="Invalid JSON")

    secret = body.get("secret", "")
    if secret != config.PAYMENT_SECRET_KEY:
        log.warning(f"Generic webhook: invalid secret from {request.remote}")
        return web.Response(status=403, text="Forbidden")

    payment_id = body.get("payment_id")
    telegram_id_raw = body.get("telegram_id")
    status = body.get("status", "")
    amount = float(body.get("amount", 0))
    plan_key = str(body.get("plan_key", "30"))

    if not payment_id or not telegram_id_raw:
        return web.Response(status=422, text="Missing payment_id or telegram_id")

    telegram_id = int(telegram_id_raw)
    log.info(f"Generic webhook received: payment_id={payment_id} telegram_id={telegram_id} status={status}")

    if status != "success":
        log.info(f"Payment not successful, status={status}")
        return web.Response(text="OK")

    await _grant_access(telegram_id, plan_key, payment_id, "generic", amount)
    return web.Response(text="OK")


# ── CryptoBot webhook ─────────────────────────────────────────────────────────

async def handle_cryptobot(request: web.Request) -> web.Response:
    body_bytes = await request.read()
    signature = request.headers.get("crypto-pay-api-signature", "")

    if config.CRYPTOBOT_TOKEN and not cryptobot.verify_webhook(body_bytes, signature):
        log.warning(f"CryptoBot webhook: invalid signature from {request.remote}")
        return web.Response(status=403, text="Forbidden")

    try:
        body = json.loads(body_bytes)
    except Exception:
        return web.Response(status=400, text="Invalid JSON")

    parsed = cryptobot.parse_webhook(body)
    if not parsed:
        return web.Response(text="OK")

    if parsed["status"] != "paid":
        return web.Response(text="OK")

    if parsed["telegram_id"] is None:
        log.warning(f"CryptoBot webhook: could not extract telegram_id from payload")
        return web.Response(text="OK")

    log.info(f"CryptoBot webhook: {parsed['payment_id']} tgid={parsed['telegram_id']}")
    await _grant_access(
        parsed["telegram_id"],
        parsed.get("plan_key", "30"),
        parsed["payment_id"],
        "cryptobot",
        parsed["amount"],
    )
    return web.Response(text="OK")


# ── Lava webhook ──────────────────────────────────────────────────────────────

async def handle_lava(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return web.Response(status=400, text="Invalid JSON")

    if config.LAVA_SECRET_KEY and not lava.verify_webhook(dict(body)):
        log.warning(f"Lava webhook: invalid signature from {request.remote}")
        return web.Response(status=403, text="Forbidden")

    parsed = lava.parse_webhook(dict(body))
    if not parsed:
        return web.Response(text="OK")

    if parsed["status"] != "success":
        log.info(f"Lava: non-success status={parsed['status']}")
        return web.Response(text="OK")

    if parsed["telegram_id"] is None:
        log.warning("Lava webhook: could not extract telegram_id from order_id")
        return web.Response(text="OK")

    log.info(f"Lava webhook: {parsed['payment_id']} tgid={parsed['telegram_id']}")
    await _grant_access(
        parsed["telegram_id"],
        parsed.get("plan_key", "30"),
        parsed["payment_id"],
        "lava",
        parsed["amount"],
    )
    return web.Response(text="OK")

async def handle_lava_verify(request: web.Request) -> web.Response:
    return web.Response(text="lava-verify=0813722c8e674ff6", content_type="text/html")


# ── Paymaster webhook ─────────────────────────────────────────────────────────

async def handle_paymaster(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return web.Response(status=400, text="Invalid JSON")

    if config.PAYMASTER_TOKEN and not paymaster.verify_webhook(dict(body)):
        log.warning(f"Paymaster webhook: invalid signature from {request.remote}")
        return web.Response(status=403, text="Forbidden")

    parsed = paymaster.parse_webhook(dict(body))
    if not parsed:
        return web.Response(text="OK")

    if parsed["status"] != "success":
        log.info(f"Paymaster: non-success status={parsed['status']}")
        return web.Response(text="OK")

    if parsed["telegram_id"] is None:
        log.warning("Paymaster webhook: could not extract telegram_id from order_id")
        return web.Response(text="OK")

    log.info(f"Paymaster webhook: {parsed['payment_id']} tgid={parsed['telegram_id']}")
    await _grant_access(
        parsed["telegram_id"],
        parsed.get("plan_key", "30"),
        parsed["payment_id"],
        "paymaster",
        parsed["amount"],
    )
    return web.Response(text="OK")


# ── Health check ──────────────────────────────────────────────────────────────

async def handle_health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "users": db.get_user_count()})


# ── App factory ───────────────────────────────────────────────────────────────

def create_app() -> web.Application:
    app = web.Application()
    app.router.add_post("/webhook/generic", handle_generic)
    app.router.add_post("/webhook/crypto", handle_cryptobot)
    app.router.add_post("/webhook/lava", handle_lava)
    app.router.add_post("/webhook/paymaster", handle_paymaster)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/lava-verify_0813722c8e674ff6.html", handle_lava_verify)
    return app


if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.dirname(__file__))

    from config import validate
    validate()
    db.init_db()
    xui.login()

    app = create_app()
    log.info(f"Webhook server starting on {config.WEBHOOK_HOST}:{config.WEBHOOK_PORT}")
    web.run_app(app, host=config.WEBHOOK_HOST, port=config.WEBHOOK_PORT)
