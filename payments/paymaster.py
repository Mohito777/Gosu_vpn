"""
Paymaster (VK Pay) payment integration.
Docs: https://paymaster.ru/docs/

Поддерживает:
  ✅ Карты Visa/MasterCard/МИР
  ✅ СБП (Система Быстрых Платежей)
  ✅ ЮMoney
  ✅ Без ИП (агентская схема)

Тестовый режим:
  - Тестовые токены начинаются с TEST:
  - Используйте тестовые карты: https://paymaster.ru/docs/test
"""

import hashlib
import hmac
import time
from typing import Optional

import requests
import config
from logger import get_logger

log = get_logger("payments.paymaster")

PAYMASTER_API = "https://api.paymaster.ru/api"


def _sign(data: dict, secret: str) -> str:
    """
    Paymaster signature: SHA256 of concatenated values.
    Order: merchant_id, order_id, amount, currency, secret
    """
    sign_string = f"{data.get('merchant_id', '')}:{data.get('order_id', '')}:{data.get('amount', '')}:{data.get('currency', 'RUB')}:{secret}"
    return hashlib.sha256(sign_string.encode("utf-8")).hexdigest().upper()


def create_invoice(
    amount: int,
    order_id: str,
    comment: str = "VPN доступ",
    success_url: str = "",
    fail_url: str = "",
    hook_url: str = "",
) -> Optional[dict]:
    """
    Create Paymaster invoice.
    Returns dict with {pay_url, order_id} on success.
    """
    # Определяем, тестовый ли режим
    is_test = "TEST" in config.PAYMASTER_TOKEN
    
    payload = {
        "merchant_id": config.PAYMASTER_MERCHANT_ID,
        "order_id": order_id,
        "amount": amount,
        "currency": "RUB",
        "description": comment,
        "success_url": success_url,
        "fail_url": fail_url,
        "callback_url": hook_url or f"https://{config.WEBHOOK_HOST}:{config.WEBHOOK_PORT}/webhook/paymaster",
        "test": "1" if is_test else "0",
    }
    
    payload["sign"] = _sign(payload, config.PAYMASTER_TOKEN)
    
    try:
        resp = requests.post(
            f"{PAYMASTER_API}/payment/create",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        data = resp.json()
        
        if data.get("status") == "success" and "pay_url" in data:
            result = {
                "pay_url": data["pay_url"],
                "order_id": order_id,
                "payment_id": data.get("payment_id", order_id),
            }
            log.info(f"Paymaster invoice created: order_id={order_id} amount={amount} test={is_test}")
            return result
        
        log.error(f"Paymaster create_invoice failed: {data}")
        return None
        
    except Exception as e:
        log.error(f"Paymaster create_invoice exception: {e}")
        return None


def verify_webhook(body: dict) -> bool:
    """Verify Paymaster webhook signature."""
    received_sign = body.pop("sign", "")
    
    # Собираем данные для проверки
    check_data = {
        "merchant_id": body.get("merchant_id", ""),
        "order_id": body.get("order_id", ""),
        "amount": body.get("amount", ""),
        "currency": body.get("currency", "RUB"),
    }
    
    computed = _sign(check_data, config.PAYMASTER_TOKEN)
    body["sign"] = received_sign  # restore
    
    return hmac.compare_digest(computed, received_sign) if received_sign else False


def parse_webhook(body: dict) -> Optional[dict]:
    """
    Parse Paymaster webhook.
    order_id format: tgid_{telegram_id}_plan_{plan_key}_{ts}
    Returns normalized dict.
    """
    try:
        order_id = body.get("order_id", "")
        status = body.get("status", "")
        payment_id = body.get("payment_id", order_id)
        
        telegram_id = None
        plan_key = None
        parts = order_id.split("_")
        # Expected: ['tgid', '12345', 'plan', '30', '1700000000']
        if len(parts) >= 4 and parts[0] == "tgid" and parts[2] == "plan":
            telegram_id = int(parts[1])
            plan_key = parts[3]
        
        # Определяем статус оплаты
        is_paid = status in ["success", "paid", "completed"]
        
        return {
            "payment_id": f"paymaster_{payment_id}",
            "telegram_id": telegram_id,
            "amount": float(body.get("amount", 0)),
            "status": "success" if is_paid else status,
            "plan_key": plan_key,
            "raw": body,
        }
    except Exception as e:
        log.error(f"Paymaster parse_webhook exception: {e}")
        return None


def make_order_id(telegram_id: int, plan_key: str) -> str:
    return f"tgid_{telegram_id}_plan_{plan_key}_{int(time.time())}"
