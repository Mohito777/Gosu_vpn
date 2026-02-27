"""
CryptoBot (Telegram) payment integration.
Docs: https://help.crypt.bot/crypto-pay-api

Принимает: TON, USDT, BTC, ETH и другие криптовалюты.
СБП: НЕ поддерживается (только крипта).
Без самозанятости / ИП — легально как p2p крипто-платёж.

Для работы:
  1. Напишите @CryptoBot (mainnet) или @CryptoTestnetBot (testnet)
  2. Создайте приложение командой /newapp
  3. Скопируйте токен в CRYPTOBOT_TOKEN в .env
"""

import hashlib
import hmac
import json
from typing import Optional

import requests
import config
from logger import get_logger

log = get_logger("payments.cryptobot")

MAINNET_API = "https://pay.crypt.bot/api"
TESTNET_API = "https://testnet-pay.crypt.bot/api"


def _api_url() -> str:
    return TESTNET_API if config.CRYPTOBOT_NETWORK == "testnet" else MAINNET_API


def _headers() -> dict:
    return {"Crypto-Pay-API-Token": config.CRYPTOBOT_TOKEN}


def create_invoice(
    amount: str,
    asset: str = "USDT",
    description: str = "VPN доступ",
    payload: str = "",
    expires_in: int = 3600,
) -> Optional[dict]:
    """
    Create a CryptoBot invoice.
    Returns invoice dict with pay_url on success, None on failure.
    payload — any string (e.g. 'tgid:12345:plan:30') for webhook identification.
    """
    try:
        resp = requests.post(
            f"{_api_url()}/createInvoice",
            headers=_headers(),
            json={
                "asset": asset,
                "amount": amount,
                "description": description,
                "payload": payload,
                "expires_in": expires_in,
                "allow_comments": False,
                "allow_anonymous": False,
            },
            timeout=10,
        )
        data = resp.json()
        if data.get("ok"):
            invoice = data["result"]
            log.info(f"CryptoBot invoice created: invoice_id={invoice['invoice_id']} amount={amount} {asset}")
            return invoice
        log.error(f"CryptoBot create_invoice failed: {data}")
        return None
    except Exception as e:
        log.error(f"CryptoBot create_invoice exception: {e}")
        return None


def get_invoice(invoice_id: int) -> Optional[dict]:
    """Poll invoice status."""
    try:
        resp = requests.get(
            f"{_api_url()}/getInvoices",
            headers=_headers(),
            params={"invoice_ids": str(invoice_id)},
            timeout=10,
        )
        data = resp.json()
        if data.get("ok") and data["result"]["items"]:
            return data["result"]["items"][0]
        return None
    except Exception as e:
        log.error(f"CryptoBot get_invoice exception: {e}")
        return None


def verify_webhook(body_bytes: bytes, crypto_pay_api_signature: str) -> bool:
    """
    Verify CryptoBot webhook signature.
    https://help.crypt.bot/crypto-pay-api#verifying-webhook-requests
    """
    secret = hashlib.sha256(config.CRYPTOBOT_TOKEN.encode()).digest()
    computed = hmac.new(secret, body_bytes, hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, crypto_pay_api_signature)


def parse_webhook(body: dict) -> Optional[dict]:
    """
    Parse CryptoBot webhook payload.
    Returns normalized dict: {payment_id, telegram_id, amount, asset, status, payload}
    """
    try:
        if body.get("update_type") != "invoice_paid":
            return None
        inv = body["payload"]
        raw_payload = inv.get("payload", "")  # e.g. "tgid:12345:plan:30"
        telegram_id = None
        plan_key = None
        for part in raw_payload.split(":"):
            pass
        # Parse payload format "tgid:XXXXX:plan:30"
        parts = raw_payload.split(":")
        if len(parts) == 4 and parts[0] == "tgid" and parts[2] == "plan":
            telegram_id = int(parts[1])
            plan_key = parts[3]
        return {
            "payment_id": f"crypto_{inv['invoice_id']}",
            "telegram_id": telegram_id,
            "amount": float(inv.get("amount", 0)),
            "asset": inv.get("asset", "USDT"),
            "status": inv.get("status", ""),
            "plan_key": plan_key,
            "raw": inv,
        }
    except Exception as e:
        log.error(f"CryptoBot parse_webhook exception: {e}")
        return None
