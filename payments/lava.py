"""
Lava.ru payment integration — карты + СБП без самозанятости / ИП.
Docs: https://dev.lava.ru/

Почему Lava:
  ✅ Принимает СБП (Система Быстрых Платежей)
  ✅ Принимает карты Visa / MasterCard / МИР
  ✅ Работает без регистрации самозанятого или ИП
  ✅ Вывод на карту физ. лица
  ⚠️  Комиссия ~5-8%, лимиты на вывод — уточняйте на сайте
  ⚠️  Частые переводы крупных сумм могут вызвать интерес банка,
      но Lava является легальным агрегатором, платёж проходит от юр. лица Lava

Альтернативы для сравнения (тоже без ИП):
  - enot.io    — аналогично, чуть дешевле комиссия
  - freekassa  — старейший агрегатор, поддерживает СБП/карты
  - crystalpay — крипта + карты
"""

import hashlib
import hmac
import json
import time
import uuid
from typing import Optional

import requests
import config
from logger import get_logger

log = get_logger("payments.lava")

LAVA_API = "https://api.lava.ru/business"


def _sign(data: dict) -> str:
    """Lava signature: HMAC-SHA256 of sorted JSON keys."""
    sorted_str = json.dumps(dict(sorted(data.items())), ensure_ascii=False, separators=(",", ":"))
    return hmac.new(
        config.LAVA_SECRET_KEY.encode("utf-8"),
        sorted_str.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def create_invoice(
    amount: int,
    order_id: str,
    comment: str = "VPN доступ",
    success_url: str = "",
    fail_url: str = "",
    hook_url: str = "",
) -> Optional[dict]:
    """
    Create Lava invoice.
    Returns dict with {url, id} on success.

    order_id format: 'tgid_{telegram_id}_plan_{plan_key}_{timestamp}'
    """
    payload = {
        "shopId": config.LAVA_SHOP_ID,
        "sum": amount,
        "orderId": order_id,
        "comment": comment,
        "successUrl": success_url,
        "failUrl": fail_url,
        "hookUrl": hook_url or f"https://{config.WEBHOOK_HOST}:{config.WEBHOOK_PORT}/webhook/lava",
        "expire": 30,  # minutes
    }
    payload["sign"] = _sign(payload)

    try:
        resp = requests.post(
            f"{LAVA_API}/invoice/create",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        data = resp.json()
        if data.get("status") == 200 and "data" in data:
            result = data["data"]
            log.info(f"Lava invoice created: id={result.get('id')} order_id={order_id} amount={amount}")
            return result
        log.error(f"Lava create_invoice failed: {data}")
        return None
    except Exception as e:
        log.error(f"Lava create_invoice exception: {e}")
        return None


def verify_webhook(body: dict) -> bool:
    """Verify Lava webhook signature."""
    received_sign = body.pop("sign", "")
    computed = _sign(body)
    body["sign"] = received_sign  # restore
    return hmac.compare_digest(computed, received_sign)


def parse_webhook(body: dict) -> Optional[dict]:
    """
    Parse Lava webhook.
    order_id format: tgid_{telegram_id}_plan_{plan_key}_{ts}
    Returns normalized dict.
    """
    try:
        order_id = body.get("orderId", "")
        status = body.get("status", "")
        payment_id = body.get("id", order_id)

        telegram_id = None
        plan_key = None
        parts = order_id.split("_")
        # Expected: ['tgid', '12345', 'plan', '30', '1700000000']
        if len(parts) >= 4 and parts[0] == "tgid" and parts[2] == "plan":
            telegram_id = int(parts[1])
            plan_key = parts[3]

        return {
            "payment_id": f"lava_{payment_id}",
            "telegram_id": telegram_id,
            "amount": float(body.get("amount", 0)),
            "status": status,  # 'success' on paid
            "plan_key": plan_key,
            "raw": body,
        }
    except Exception as e:
        log.error(f"Lava parse_webhook exception: {e}")
        return None


def make_order_id(telegram_id: int, plan_key: str) -> str:
    return f"tgid_{telegram_id}_plan_{plan_key}_{int(time.time())}"
