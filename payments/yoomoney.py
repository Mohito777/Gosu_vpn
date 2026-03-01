"""
YooMoney payment integration — карты + СБП.
Docs: https://yoomoney.ru/docs/

Принимает:
  ✅ Карты Visa/MasterCard/МИР
  ✅ СБП (Система Быстрых Платежей)
  ✅ ЮMoney кошельки

Для работы:
  1. Зарегистрируйся на https://yoomoney.ru
  2. Получи API ключ в кабинете
  3. Добавь YOUMONEY_API_KEY в .env
"""

import hashlib
import hmac
import time
from typing import Optional

import requests
import config
from logger import get_logger

log = get_logger("payments.yoomoney")

YOOMONEY_API = "https://yoomoney.ru/api"


def create_invoice(
    amount: int,
    order_id: str,
    comment: str = "VPN доступ",
    success_url: str = "",
    fail_url: str = "",
    webhook_url: str = "",
) -> Optional[dict]:
    """
    Create YooMoney invoice.
    Returns dict with {pay_url, invoice_id} on success.
    
    order_id format: 'tgid_{telegram_id}_plan_{plan_key}_{timestamp}'
    """
    payload = {
        "pattern_id": "p2p",
        "to": config.YOUMONEY_ACCOUNT,
        "amount": amount,
        "comment": comment,
        "message": order_id,
        "label": order_id,
    }
    
    try:
        # Используем HTTP API для создания счёта
        resp = requests.post(
            f"{YOOMONEY_API}/transfer",
            data=payload,
            headers={
                "Authorization": f"Bearer {config.YOUMONEY_API_KEY}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=10,
        )
        data = resp.json()
        
        if data.get("status") == "success":
            invoice_id = data.get("request_id", order_id)
            pay_url = f"https://yoomoney.ru/to/{config.YOUMONEY_ACCOUNT}/{amount}?comment={order_id}"
            result = {
                "pay_url": pay_url,
                "invoice_id": invoice_id,
                "order_id": order_id,
            }
            log.info(f"YooMoney invoice created: id={invoice_id} order_id={order_id} amount={amount}")
            return result
        
        log.error(f"YooMoney create_invoice failed: {data}")
        return None
        
    except Exception as e:
        log.error(f"YooMoney create_invoice exception: {e}")
        return None


def verify_webhook(body: dict, signature: str) -> bool:
    """
    Verify YooMoney webhook signature.
    Signature = HMAC-SHA1 of notification parameters
    """
    if not config.YOUMONEY_SECRET:
        return True  # Если секрет не настроен — пропускаем
    
    # Формируем строку для проверки
    # notification_type&operation_id&amount&currency&datetime&sender&codepro&label
    check_string = "&".join([
        str(body.get("notification_type", "")),
        str(body.get("operation_id", "")),
        str(body.get("amount", "")),
        str(body.get("currency", "")),
        str(body.get("datetime", "")),
        str(body.get("sender", "")),
        str(body.get("codepro", "")),
        str(body.get("label", "")),
    ])
    
    computed = hashlib.sha1((check_string + config.YOUMONEY_SECRET).encode()).hexdigest()
    return hmac.compare_digest(computed, signature)


def parse_webhook(body: dict) -> Optional[dict]:
    """
    Parse YooMoney webhook.
    order_id format: tgid_{telegram_id}_plan_{plan_key}_{ts}
    Returns normalized dict.
    """
    try:
        # YooMoney отправляет уведомление о поступлении средств
        notification_type = body.get("notification_type", "")
        
        if notification_type != "p2p-incoming":
            return None
        
        label = body.get("label", "")  # Это наш order_id
        amount = float(body.get("amount", 0))
        operation_id = body.get("operation_id", label)
        
        telegram_id = None
        plan_key = None
        
        # Parse label: tgid_12345_plan_30_1700000000
        parts = label.split("_")
        if len(parts) >= 4 and parts[0] == "tgid" and parts[2] == "plan":
            telegram_id = int(parts[1])
            plan_key = parts[3]
        
        return {
            "payment_id": f"yoomoney_{operation_id}",
            "telegram_id": telegram_id,
            "amount": amount,
            "status": "success",  # Если пришло уведомление — оплата прошла
            "plan_key": plan_key,
            "raw": body,
        }
        
    except Exception as e:
        log.error(f"YooMoney parse_webhook exception: {e}")
        return None


def make_order_id(telegram_id: int, plan_key: str) -> str:
    return f"tgid_{telegram_id}_plan_{plan_key}_{int(time.time())}"
